#!/usr/bin/env python3
"""Prepare bounded candidate coverage before a later prospective decision."""
import argparse
import fcntl
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    import agent_db
    from agents.learning.macro_coverage import preparation_targets, score_candidates, certify, reconcile_runs, coverage_row
    from agents.learning.macro_provenance import accepted_contract, DIMS, snapshot
    parser = argparse.ArgumentParser()
    parser.add_argument("--prepare", action="store_true", help="Fetch existing financial sources, score, and certify envelope targets")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    report = preparation_targets()
    if args.prepare:
        with (ROOT / "out/macro_candidate_preparation.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            agent_db.migrate()
            conn = agent_db._connect()
            try:
                acc = accepted_contract(conn, time.time())
                if not acc:
                    raise RuntimeError("Current formal acceptance is required before candidate preparation")
                reconcile_runs(conn, time.time())  # exclusive process lock proves no live collector
                targets = [r["ticker"] for r in report["envelope"]]
                if not targets:
                    raise RuntimeError("No base-eligible candidates")
                from financials_fetcher import fetch_all
                fetch_all(targets)
                report["scoring_run_id"] = score_candidates(conn, targets)
                run = conn.execute("SELECT status FROM macro_candidate_scoring_runs WHERE run_id=?", (report["scoring_run_id"],)).fetchone()
                if run[0] != "COMPLETE":
                    raise RuntimeError("Candidate scoring incomplete; inspect candidate run ledger")
                pending = []
                for ticker in targets:
                    # Original accepted eligibility or completed supplemental certification
                    # is reusable under this exact contract. Runtime scores cannot substitute.
                    original = conn.execute("SELECT COUNT(*) FROM macro_dimension_validation WHERE acceptance_record_id=? AND ticker=? AND n_samples=20 AND scorer_contract_hash=? AND config_hash=? AND model_identity=?",
                                            (acc["record_id"], ticker, acc["scorer_contract_hash"], acc["config_hash"], acc["model_identity"])).fetchone()[0]
                    if original != len(DIMS) and not all(coverage_row(conn, acc, ticker, d, time.time()) for d in DIMS):
                        pending.append(ticker)
                report["certification_id"] = certify(conn, pending) if pending else None
                report["acceptance"] = acc
                report["coverage"] = {t: snapshot(t, conn, time.time()) for t in targets}
                report["completed_at"] = time.time()
            finally:
                conn.close()
    output = json.dumps(report, indent=2, allow_nan=False)
    if args.out:
        with args.out.open("x") as f:
            f.write(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
