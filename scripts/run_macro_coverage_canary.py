#!/usr/bin/env python3
"""Real Opportunity Hunter handler, isolated parity replay, no broker execution."""
import argparse
import copy
import json
import sqlite3
import sys
import tempfile
import time
import uuid
from contextlib import ExitStack
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def normalized_recommendations(recs):
    # These two fields identify/time-stamp the distinct replay, not recommendation behavior.
    return [{k: v for k, v in asdict(r).items() if k not in ("episode_id", "valid_until")} for r in recs]


def run(out):
    import agent_db
    from agents import opportunity_agent as oa
    from agents.contracts import AgentContext
    from agents.snapshot import build_portfolio_snapshot
    from agents.learning import macro_experiment as mx
    from agents.learning.macro_provenance import canonical, digest

    if out.exists():
        raise FileExistsError(out)
    agent_db.migrate()
    cid = str(uuid.uuid4())
    winners, manual = oa._get_buffett_winners(), oa._get_manual_candidates()
    held, weights = oa._get_current_tickers(), oa._get_layer_weights()
    sectors = oa._get_holding_sectors(held)
    portfolio = build_portfolio_snapshot()
    production_db = agent_db.DB_PATH
    conn = agent_db._connect()
    before_intents = conn.execute("SELECT COUNT(*) FROM trade_intents").fetchone()[0]
    artifact = {"canary_id": cid, "status": "FAILED", "stage": 0, "production_macro_weight": 0,
                "code_commit": agent_db.CODE_COMMIT_SHA, "started_at": time.time()}
    cohort = None
    try:
        with tempfile.TemporaryDirectory(prefix="macro-canary-") as tmp, ExitStack() as stack:
            baseline_path = Path(tmp) / "baseline.db"
            with sqlite3.connect(baseline_path) as baseline:
                conn.backup(baseline)
            conn.close()
            for name, value in (("_get_buffett_winners", winners), ("_get_manual_candidates", manual),
                                ("_get_current_tickers", held), ("_get_layer_weights", weights),
                                ("_get_holding_sectors", sectors)):
                stack.enter_context(patch.object(oa, name, lambda *args, value=value: copy.deepcopy(value)))
            original_llm = oa._llm_select
            llm_calls = []

            def capture_llm(candidates, layers):
                result = original_llm(candidates, layers)
                llm_calls.append((copy.deepcopy(candidates), copy.deepcopy(layers), copy.deepcopy(result)))
                return result

            actual_id = agent_db.insert_agent_run("opportunity_hunter", trigger_type="macro_coverage_canary")
            actual_started = time.time()
            with patch.object(oa, "_llm_select", capture_llm):
                actual = oa.run_opportunity_hunter(AgentContext(actual_id, portfolio, "macro_coverage_canary"))
            actual_finished = time.time()
            agent_db.finish_agent_run(actual_id)
            with agent_db._connect() as c:
                found = c.execute("SELECT * FROM macro_experiment_cohorts WHERE agent_run_id=? ORDER BY captured_at DESC LIMIT 1", (str(actual_id),)).fetchone()
                if found:
                    cohort = dict(found)
            if not cohort or cohort["status"] != "OBSERVED":
                raise ValueError("real sweep did not produce an OBSERVED coverage-complete cohort: " + str(cohort and cohort["exclusion_reason"]))

            def replay_llm(candidates, layers):
                if len(llm_calls) != 1:
                    raise ValueError("missing unique real LLM response")
                prior, prior_layers, response = llm_calls[0]
                normalize = lambda rows: [{k: v for k, v in row.items() if k != "_episode_id"} for row in rows]
                if normalize(candidates) != normalize(prior) or layers != prior_layers:
                    raise ValueError("production candidate inputs changed during isolated replay")
                return copy.deepcopy(response)

            def baseline_connect():
                replay_conn = sqlite3.connect(baseline_path, timeout=10)
                replay_conn.row_factory = sqlite3.Row
                replay_conn.execute("PRAGMA foreign_keys=ON")
                return replay_conn

            with patch.object(agent_db, "DB_PATH", baseline_path), patch.object(agent_db, "_connect", baseline_connect), patch.object(mx, "register_epoch", lambda conn: None), patch.object(oa, "_llm_select", replay_llm):
                baseline_id = agent_db.insert_agent_run("opportunity_hunter", trigger_type="macro_disabled_parity_replay")
                replay_started = time.time()
                baseline = oa.run_opportunity_hunter(AgentContext(baseline_id, portfolio, "macro_coverage_canary"))
                replay_finished = time.time()
            parity = normalized_recommendations(actual) == normalized_recommendations(baseline)
            if not parity:
                raise ValueError("production output differs with macro observation enabled")
            for recs, start, end in ((actual, actual_started, actual_finished), (baseline, replay_started, replay_finished)):
                if any(not start + 7 * 86400 <= r.valid_until <= end + 7 * 86400 for r in recs):
                    raise ValueError("recommendation validity horizon changed")
            conn = agent_db._connect()
            if conn.execute("SELECT COUNT(*) FROM trade_intents").fetchone()[0] != before_intents:
                raise ValueError("trade intent count changed during canary")
            books = {}
            for bid in mx._book_ids(cohort["epoch_id"]):
                book = conn.execute("SELECT * FROM virtual_books WHERE book_id=?", (bid,)).fetchone()
                fills = conn.execute("SELECT * FROM virtual_fills WHERE book_id=?", (bid,)).fetchall()
                if book is None or not fills:
                    raise ValueError("both virtual books must have real recorded shadow fills")
                books[bid] = {"book": dict(book), "fills": [dict(r) for r in fills], "metrics": mx._book_report(conn, bid)}
            if cohort["book_status"] != "RECORDED":
                raise ValueError("paired virtual book capture incomplete")
            artifact.update(status="PASS", epoch_id=cohort["epoch_id"], cohort=cohort,
                            production_parity=parity, recommendation=normalized_recommendations(actual),
                            llm_response=llm_calls[0][2] if llm_calls else None,
                            common_dimensions=json.loads(cohort["dimensions_json"]), books=books,
                            coverage=dict(conn.execute("SELECT * FROM macro_experiment_coverage WHERE cohort_id=?", (cohort["cohort_id"],)).fetchone()),
                            trade_intents_unchanged=True, production_handler_executed=True,
                            recommendation_published=False, live_trades_executed=False)
    except Exception as exc:
        artifact["error"] = str(exc)
    finally:
        if conn:
            conn.close()
        artifact["completed_at"] = time.time()
        with out.open("x") as f:
            f.write(json.dumps(artifact, indent=2, allow_nan=False) + "\n")
        if cohort:
            with agent_db._connect() as c:
                c.execute("INSERT INTO macro_experiment_canaries VALUES (?,?,?,?,?,?)",
                          (cid, cohort["epoch_id"], cohort["cohort_id"], artifact["completed_at"], artifact["status"], canonical(artifact)))
            c.close()
    print(json.dumps({"artifact": str(out), "status": artifact["status"], "error": artifact.get("error"), "canary_id": cid}))
    return artifact["status"] == "PASS"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sys.exit(0 if run(args.out) else 1)
