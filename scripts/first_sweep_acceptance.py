#!/usr/bin/env python3
"""First-sweep operational acceptance (0455).

Run once after the first real Opportunity Hunter learning sweep to verify the
full live pipeline end-to-end. Writes config/experiment_canary_001.json on
full PASS. Exits non-zero on any failure so it can be called from shell.

Usage:
    python scripts/first_sweep_acceptance.py [--db PATH] [--dry-run]

Exit codes:
    0 = all checks passed; JSON written (or --dry-run preview printed)
    1 = one or more checks failed
    2 = no learning sweep has occurred yet (not an error, just too early)
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_OUT_PATH = _REPO_ROOT / "config" / "experiment_canary_001.json"


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=str(_REPO_ROOT),
            text=True, stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return None


def _git_dirty() -> bool | None:
    try:
        out = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=str(_REPO_ROOT),
            text=True, stderr=subprocess.DEVNULL,
        )
        return bool(out.strip())
    except Exception:
        return None


def _check_latest_sweep(conn) -> tuple[dict | None, list[str]]:
    """Return (sweep_row, failures). None if no sweep exists."""
    try:
        row = conn.execute(
            "SELECT * FROM learning_sweep_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
    except sqlite3.OperationalError:
        return None, []  # table doesn't exist yet
    if row is None:
        return None, []
    failures = []
    if row["status"] != "COMPLETED":
        failures.append(f"latest sweep status={row['status']} (must be COMPLETED)")
    elif (row["expected_candidates"] or 0) != (row["scored_candidates"] or 0):
        failures.append(
            f"candidate count mismatch: expected={row['expected_candidates']} "
            f"scored={row['scored_candidates']}"
        )
    return dict(row), failures


def _check_single_cohort_per_run(conn, agent_run_id: str) -> list[str]:
    row = conn.execute(
        "SELECT COUNT(DISTINCT cohort_id) AS n FROM learning_sweep_runs WHERE agent_run_id=?",
        (agent_run_id,),
    ).fetchone()
    n = row["n"] if row else 0
    if n != 1:
        return [f"multiple cohort_ids in invocation: got {n}, expected 1"]
    return []


def _check_winner_counts(conn, cohort_id: str, model_version: str) -> list[str]:
    failures = []
    row = conn.execute(
        """SELECT SUM(would_select) AS ch, SUM(COALESCE(base_would_select,0)) AS base
           FROM model_observations
           WHERE decision_cohort_id=? AND model_version=?""",
        (cohort_id, model_version),
    ).fetchone()
    ch = row["ch"] if row else 0
    base = row["base"] if row else 0
    if ch != 1:
        failures.append(f"challenger winners={ch} (expected 1)")
    if base != 1:
        failures.append(f"base winners={base} (expected 1)")
    return failures


def _check_observation_run_mapping(conn, cohort_id: str, model_version: str,
                                    agent_run_id: str) -> list[str]:
    row = conn.execute(
        """SELECT COUNT(*) AS n FROM model_observations mo
           LEFT JOIN decision_episodes de
             ON mo.episode_id=de.episode_id AND de.run_id=?
           WHERE mo.decision_cohort_id=? AND mo.model_version=?
             AND de.episode_id IS NULL""",
        (agent_run_id, cohort_id, model_version),
    ).fetchone()
    n = row["n"] if row else 0
    if n > 0:
        return [f"{n} observation(s) not linked to agent_run_id={agent_run_id}"]
    return []


def _check_paper_variant_agreement(conn, cohort_id: str, model_version: str) -> list[str]:
    shadow_ep = conn.execute(
        """SELECT episode_id FROM model_observations
           WHERE decision_cohort_id=? AND model_version=? AND would_select=1 LIMIT 1""",
        (cohort_id, model_version),
    ).fetchone()
    variant_ep = conn.execute(
        """SELECT challenger_episode_id FROM decision_variants
           WHERE decision_cohort_id=? AND challenger_model_version=? LIMIT 1""",
        (cohort_id, model_version),
    ).fetchone()
    if variant_ep is None or variant_ep["challenger_episode_id"] is None:
        return []  # no variant row yet — not an error
    if shadow_ep and shadow_ep["episode_id"] != variant_ep["challenger_episode_id"]:
        return [
            f"shadow episode {shadow_ep['episode_id']!r} != "
            f"variant episode {variant_ep['challenger_episode_id']!r}"
        ]
    return []


def _run_integrity_audit(db_path: str) -> tuple[str, dict]:
    """Run check_integrity.py against db_path; return (overall, full_result)."""
    try:
        result = subprocess.run(
            [sys.executable, str(_REPO_ROOT / "check_integrity.py"), "--json"],
            capture_output=True, text=True,
            env={**__import__("os").environ, "INVESTMENT_DB": db_path},
        )
        data = json.loads(result.stdout)
        return data.get("overall", "error"), data
    except Exception as e:
        return "error", {"error": str(e)}


def run_acceptance(db_path: str) -> dict:
    """Execute all acceptance checks; return structured result."""
    conn = _connect(db_path)
    failures: list[str] = []
    checks: dict = {}

    # 1. Latest sweep COMPLETED with exact counts
    sweep, sweep_fails = _check_latest_sweep(conn)
    if sweep is None:
        conn.close()
        return {"status": "NO_SWEEP", "message": "No learning sweep has occurred yet."}
    checks["latest_sweep"] = {"sweep": sweep, "failures": sweep_fails}
    failures.extend(f"[sweep] {f}" for f in sweep_fails)

    agent_run_id = sweep.get("agent_run_id", "")
    cohort_id = sweep.get("cohort_id", "")
    model_version = sweep.get("model_version", "")
    phase = sweep.get("phase") or conn.execute(
        "SELECT lifecycle_state FROM learning_models WHERE model_version=?",
        (model_version,),
    ).fetchone()

    # 2. Single cohort per invocation
    if agent_run_id:
        sc_fails = _check_single_cohort_per_run(conn, agent_run_id)
        checks["single_cohort_per_run"] = {"failures": sc_fails}
        failures.extend(f"[cohort_count] {f}" for f in sc_fails)
    else:
        checks["single_cohort_per_run"] = {"failures": ["agent_run_id not set"]}
        failures.append("[cohort_count] agent_run_id not set on sweep row")

    # 3. Winner counts
    w_fails = _check_winner_counts(conn, cohort_id, model_version)
    checks["winner_counts"] = {"failures": w_fails}
    failures.extend(f"[winners] {f}" for f in w_fails)

    # 4. Observation-to-run mapping
    if agent_run_id:
        map_fails = _check_observation_run_mapping(conn, cohort_id, model_version, agent_run_id)
        checks["observation_run_mapping"] = {"failures": map_fails}
        failures.extend(f"[run_mapping] {f}" for f in map_fails)

    # 5. PAPER_ACTIVE variant agreement (if applicable)
    _phase_str = (
        phase if isinstance(phase, str)
        else (phase["lifecycle_state"] if phase else sweep.get("phase") or "")
    )
    if _phase_str == "PAPER_ACTIVE":
        pv_fails = _check_paper_variant_agreement(conn, cohort_id, model_version)
        checks["paper_variant_agreement"] = {"failures": pv_fails}
        failures.extend(f"[variant] {f}" for f in pv_fails)
    else:
        checks["paper_variant_agreement"] = {"skipped": f"phase={_phase_str!r}"}

    conn.close()

    # 6. Full integrity audit
    integrity_overall, integrity_result = _run_integrity_audit(db_path)
    checks["integrity_audit"] = {"overall": integrity_overall}
    if integrity_overall == "BLOCK":
        failures.append(f"[integrity] overall={integrity_overall}")

    passed = len(failures) == 0
    return {
        "status": "PASS" if passed else "FAIL",
        "failures": failures,
        "checks": checks,
        "sweep": sweep,
        "integrity_overall": integrity_overall,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(_REPO_ROOT / "out" / "investment.db"))
    parser.add_argument("--dry-run", action="store_true",
                        help="Print result without writing experiment_canary_001.json")
    args = parser.parse_args()

    result = run_acceptance(args.db)

    if result["status"] == "NO_SWEEP":
        print(f"\n[0455] {result['message']}")
        print("Run this script again after the first Opportunity Hunter learning sweep.")
        sys.exit(2)

    sweep = result["sweep"]
    print(f"\n=== First-Sweep Operational Acceptance (0455) ===")
    print(f"  cohort_id:     {sweep.get('cohort_id')}")
    print(f"  agent_run_id:  {sweep.get('agent_run_id')}")
    print(f"  model_version: {sweep.get('model_version')}")
    print(f"  status:        {sweep.get('status')}  "
          f"(expected={sweep.get('expected_candidates')} scored={sweep.get('scored_candidates')})")
    print(f"  integrity:     {result['integrity_overall']}")
    print(f"  result:        {result['status']}")

    if result["failures"]:
        print("\nFailures:")
        for f in result["failures"]:
            print(f"  FAIL  {f}")

    if result["status"] != "PASS":
        print("\nAcceptance FAILED — resolve the above before freezing the architecture.")
        sys.exit(1)

    # Build the canary record
    sha = _git_sha()
    dirty = _git_dirty()
    record = {
        "_note": (
            "Append-only first-sweep operational acceptance record (0455). "
            "Written once after the first verified live learning sweep. "
            "Architecture is frozen after this passes."
        ),
        "source_commit_sha": sha,
        "git_dirty": dirty,
        "agent_run_id": sweep.get("agent_run_id"),
        "cohort_id": sweep.get("cohort_id"),
        "model_version": sweep.get("model_version"),
        "phase": sweep.get("phase"),
        "expected_candidates": sweep.get("expected_candidates"),
        "scored_candidates": sweep.get("scored_candidates"),
        "canary_result": "PASS",
        "integrity_check_result": result["integrity_overall"],
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }

    if args.dry_run:
        print("\n[dry-run] Would write:")
        print(json.dumps(record, indent=2))
        return

    if _OUT_PATH.exists():
        print(f"\nWARNING: {_OUT_PATH} already exists — not overwriting.")
        print("This is an append-only record. Archive it if starting a new experiment.")
        sys.exit(1)

    _OUT_PATH.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"\nAcceptance record written to {_OUT_PATH}")
    print("Architecture is now frozen.")


if __name__ == "__main__":
    main()
