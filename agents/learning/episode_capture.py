"""Decision Episode capture layer (0327).

Stores an immutable feature snapshot for every scored candidate in the
Opportunity Hunter before sorting or thresholding. These rows are the
training corpus for the future Strategy Learning Loop.

Call order from opportunity_agent.run_opportunity_hunter():
  1. capture_candidate_episode(run_id, candidate) → episode_id
     Called for every scored candidate, before sort.
  2. update_episode_ranks([(episode_id, rank), ...])
     Called once after scored list is sorted (rank 1 = best composite).
  3. mark_episode_selected(episode_id, llm_why=...)
     Called once after the LLM or fallback picks the winner.

Rows are append-only after capture. Only candidate_rank, selected, llm_why,
and llm_conviction are updated after initial insert.
"""
from __future__ import annotations

import json
import time
import uuid

import agent_db

_FEATURE_SCHEMA_VERSION = "v1"


def _build_macro_snapshot(ticker: str, conn) -> str:
    """Load latest macro scores for ticker and build macro_snapshot JSON (0494/0497/0500)."""
    try:
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
        from portfolio_ai import (is_fund, _classify_macro_coverage,
                                   _get_macro_acceptance_state, DB_PATH)
        import sqlite3 as _sqlite3

        coverage_state = _classify_macro_coverage(ticker, conn)

        if coverage_state == "fund_unsupported":
            snap = {"macro_supported": False, "coverage_state": "fund_unsupported",
                    "reason": "fund/etf — no constituent evidence"}
        elif coverage_state == "no_score_available":
            snap = {"macro_supported": False, "coverage_state": "no_score_available",
                    "reason": "company ticker but no macro score row"}
        elif coverage_state == "stale_score":
            snap = {"macro_supported": False, "coverage_state": "stale_score",
                    "reason": f"score older than 14 days"}
        else:
            row = conn.execute(
                "SELECT scores, scored_at FROM holding_macro_scores "
                "WHERE ticker=? ORDER BY scored_at DESC LIMIT 1",
                (ticker,)
            ).fetchone()
            if not row:
                snap = {"macro_supported": False, "coverage_state": "no_score_available",
                        "reason": "no macro scores available"}
            else:
                scores_json, scored_at = row[0], row[1]
                try:
                    scores = json.loads(scores_json)
                except Exception:
                    snap = {"macro_supported": False, "coverage_state": "no_score_available",
                            "reason": "scores parse error"}
                    scores = None
                if scores is not None:
                    snap = {
                        "macro_supported":            True,
                        "coverage_state":             "company_supported",
                        "rate_sensitivity":           scores.get("rate_sensitivity"),
                        "dollar_sensitivity":         scores.get("dollar_sensitivity"),
                        "inflation_hedge":            scores.get("inflation_hedge"),
                        "geopolitical_risk":          scores.get("geopolitical_risk"),
                        "evidence_quality":           scores.get("evidence_quality"),
                        "rate_beta_100bp_return_pct": scores.get("rate_beta_100bp_return_pct"),
                        "usd_beta_1pct_return_pct":   scores.get("usd_beta_1pct_return_pct"),
                        "rate_beta_confidence":       scores.get("rate_beta_confidence"),
                        "run_id":                     scores.get("run_id"),
                        "model_version":              scores.get("model_version"),
                        "schema_version":             scores.get("schema_version"),
                        "evidence_hash":              scores.get("evidence_hash"),
                        "scored_at":                  scored_at,
                        # 0506/0509: per-dim usability and stability for attribution gate
                        "rate_sensitivity_usable_for_attribution":
                            scores.get("rate_sensitivity_usable_for_attribution"),
                        "dollar_sensitivity_usable_for_attribution":
                            scores.get("dollar_sensitivity_usable_for_attribution"),
                        "inflation_hedge_usable_for_attribution":
                            scores.get("inflation_hedge_usable_for_attribution"),
                        "geopolitical_risk_usable_for_attribution":
                            scores.get("geopolitical_risk_usable_for_attribution"),
                        "rate_sensitivity_stability_class":
                            scores.get("rate_sensitivity_stability_class"),
                        "dollar_sensitivity_stability_class":
                            scores.get("dollar_sensitivity_stability_class"),
                        "inflation_hedge_stability_class":
                            scores.get("inflation_hedge_stability_class"),
                        "geopolitical_risk_stability_class":
                            scores.get("geopolitical_risk_stability_class"),
                    }

        # 0497: tag validation status
        try:
            conn_ac = _sqlite3.connect(str(DB_PATH), timeout=5)
            acceptance = _get_macro_acceptance_state(conn_ac)
            conn_ac.close()
        except Exception:
            acceptance = {}
        if acceptance:
            snap["macro_validation_status"]    = "ACCEPTED"
            snap["macro_validation_contract"]  = acceptance.get("contract")
            snap["macro_validation_record_id"] = acceptance.get("record_id")
        else:
            snap["macro_validation_status"]    = "PRE_ACCEPTANCE"
            snap["macro_validation_contract"]  = None
            snap["macro_validation_record_id"] = None

        return json.dumps(snap)
    except Exception as e:
        return json.dumps({"macro_supported": False, "reason": f"error: {e}"})


def capture_candidate_episode(
    run_id: int,
    candidate: dict,
    portfolio_snapshot: dict | None = None,
) -> str:
    """Insert one immutable episode row for a scored candidate.

    Returns the new episode_id. Failures are logged and swallowed so
    a DB error never interrupts the main recommendation flow.
    """
    episode_id = str(uuid.uuid4())
    base_score = candidate.get("_composite")  # 0331: explicit base score before any challenger
    try:
        snapshot_json = json.dumps(portfolio_snapshot) if portfolio_snapshot else None
        conn = agent_db._connect()
        conn.execute(
            """
            INSERT OR IGNORE INTO decision_episodes (
                episode_id, run_id, ticker, captured_at,
                candidate_rank, selected,
                q_score, v_score, pf_score, c_score, ec_score, composite_score,
                buffett_score, pe_ratio, p_fcf, ev_ebitda,
                gross_margin, net_income_margin, sga_margin, capex_margin,
                market_cap, layer_rec, sector, industry, value_trap_risk,
                llm_model, prompt_version, feature_schema_version,
                portfolio_snapshot_json, base_score, code_commit_sha
            ) VALUES (
                ?,?,?,?,
                NULL,0,
                ?,?,?,?,?,?,
                ?,?,?,?,
                ?,?,?,?,
                ?,?,?,?,?,
                ?,?,?,
                ?,?,?
            )
            """,
            (
                episode_id, run_id, candidate["ticker"], time.time(),
                candidate.get("_q"), candidate.get("_v"),
                candidate.get("_pf"), candidate.get("_c"),
                candidate.get("_ec"), candidate.get("_composite"),
                candidate.get("quality_score"), candidate.get("pe_ratio"),
                candidate.get("p_fcf"), candidate.get("ev_ebitda"),
                candidate.get("gross_margin"), candidate.get("net_income_margin"),
                candidate.get("sga_margin"), candidate.get("capex_margin"),
                candidate.get("market_cap"), candidate.get("layer_rec"),
                candidate.get("sector"), candidate.get("industry"),
                candidate.get("value_trap_risk"),
                "mlx-community/Qwen3.6-35B-A3B-4bit",
                "opportunity_hunter_v1",
                _FEATURE_SCHEMA_VERSION,
                snapshot_json, base_score, agent_db.CODE_COMMIT_SHA,
            ),
        )
        # Attach macro snapshot read-only (0494) — never influences scoring/ranking
        try:
            macro_snap_json = _build_macro_snapshot(candidate["ticker"], conn)
            conn.execute(
                "UPDATE decision_episodes SET macro_snapshot=? "
                "WHERE episode_id=? AND macro_snapshot IS NULL",
                (macro_snap_json, episode_id),
            )
        except Exception as snap_e:
            print(f"[episode_capture] WARNING: macro_snapshot attachment failed for "
                  f"{candidate.get('ticker')}: {snap_e}")
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[episode_capture] WARNING: failed to capture episode for "
              f"{candidate.get('ticker')}: {e}")
    return episode_id


def update_episode_ranks(episodes: list[tuple[str, int]]) -> None:
    """Set candidate_rank on each episode after the scored list is sorted.

    episodes: [(episode_id, rank), ...] where rank 1 = highest composite.
    """
    if not episodes:
        return
    try:
        conn = agent_db._connect()
        for episode_id, rank in episodes:
            conn.execute(
                "UPDATE decision_episodes SET candidate_rank=? WHERE episode_id=?",
                (rank, episode_id),
            )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[episode_capture] WARNING: failed to update episode ranks: {e}")


def mark_episode_selected(
    episode_id: str,
    llm_why: str | None = None,
    llm_conviction: int | None = None,
    challenger_score: float | None = None,
    challenger_model_version: str | None = None,
) -> None:
    """Mark the winner episode as selected=1 and store LLM rationale and challenger info."""
    try:
        conn = agent_db._connect()
        conn.execute(
            """UPDATE decision_episodes
               SET selected=1, llm_why=?, llm_conviction=?,
                   challenger_score=?, challenger_model_version=?
               WHERE episode_id=?""",
            (llm_why, llm_conviction, challenger_score, challenger_model_version, episode_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[episode_capture] WARNING: failed to mark episode selected: {e}")


def update_episode_challenger_info(
    episode_id: str,
    challenger_score: float | None,
    challenger_model_version: str | None,
) -> None:
    """Update challenger score and model version on any episode after the challenger runs."""
    try:
        conn = agent_db._connect()
        conn.execute(
            """UPDATE decision_episodes
               SET challenger_score=?, challenger_model_version=?
               WHERE episode_id=?""",
            (challenger_score, challenger_model_version, episode_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[episode_capture] WARNING: failed to update challenger info: {e}")
