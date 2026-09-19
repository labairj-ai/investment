#!/usr/bin/env python3
"""First-sweep operational acceptance (0455/0456/0457/0458).

Two milestones, two artifacts:

  --mode shadow  (default)
      After the first successful OBSERVE sweep.  Validates the observation
      pipeline: OH → ledger → shadow scoring → episode lineage → winner counts.
      Writes config/experiment_shadow_canary_001.json.
      Meaning: "observation pipeline verified" — NOT "architecture frozen."

  --mode paper
      After the first base-eligible PAPER_ACTIVE sweep.  Runs all shadow
      checks plus: variant row exists and challenger_episode_id matches the
      shadow winner.  Writes config/experiment_paper_canary_001.json.
      Meaning: "full learning-to-paper architecture validated."

Exit codes:
    0 = all checks passed; artifact written (or --dry-run preview shown)
    1 = one or more checks failed
    2 = no qualifying sweep found yet (not an error — too early)
    3 = clean-git or integrity requirement not met before artifact write
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
_SHADOW_OUT = _REPO_ROOT / "config" / "experiment_shadow_canary_001.json"
_PAPER_OUT  = _REPO_ROOT / "config" / "experiment_paper_canary_001.json"

_HEALTHY_INTEGRITY = {"ok"}   # 0457: only "ok" is acceptable for a freeze record


# ─────────────────────────────────────────────────────────────────────────────
# Git helpers
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────────────

def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _col(row, name, default=None):
    try:
        return row[name]
    except (IndexError, KeyError):
        return default


# ─────────────────────────────────────────────────────────────────────────────
# Sweep locators
# ─────────────────────────────────────────────────────────────────────────────

def _find_shadow_sweep(conn) -> dict | None:
    """Latest COMPLETED OBSERVE sweep, or None."""
    try:
        row = conn.execute(
            """SELECT * FROM learning_sweep_runs
               WHERE phase='OBSERVE' AND status='COMPLETED'
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(row) if row else None


def _find_paper_sweep(conn) -> dict | None:
    """Latest COMPLETED PAPER_ACTIVE sweep with base_recommendation_eligible=1, or None."""
    try:
        row = conn.execute(
            """SELECT * FROM learning_sweep_runs
               WHERE phase='PAPER_ACTIVE'
                 AND status='COMPLETED'
                 AND base_recommendation_eligible=1
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return dict(row) if row else None


# ─────────────────────────────────────────────────────────────────────────────
# Individual checks
# ─────────────────────────────────────────────────────────────────────────────

def _check_sweep_counts(sweep: dict) -> list[str]:
    exp = sweep.get("expected_candidates") or 0
    sco = sweep.get("scored_candidates") or 0
    if exp != sco:
        return [f"candidate count mismatch: expected={exp} scored={sco}"]
    return []


def _check_single_cohort_per_run(conn, agent_run_id: str) -> list[str]:
    try:
        row = conn.execute(
            "SELECT COUNT(DISTINCT cohort_id) AS n FROM learning_sweep_runs WHERE agent_run_id=?",
            (agent_run_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return ["learning_sweep_runs table unavailable"]
    n = row["n"] if row else 0
    return [] if n == 1 else [f"multiple cohort_ids in invocation: got {n}, expected 1"]


def _check_winner_counts(conn, cohort_id: str, model_version: str) -> list[str]:
    row = conn.execute(
        """SELECT SUM(would_select) AS ch, SUM(COALESCE(base_would_select,0)) AS base
           FROM model_observations
           WHERE decision_cohort_id=? AND model_version=?""",
        (cohort_id, model_version),
    ).fetchone()
    ch   = int(row["ch"]   or 0) if row else 0
    base = int(row["base"] or 0) if row else 0
    failures = []
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
    n = int(row["n"] or 0) if row else 0
    return [] if n == 0 else [f"{n} observation(s) not linked to agent_run_id={agent_run_id}"]


def _check_paper_variant_agreement(conn, cohort_id: str, model_version: str,
                                    base_eligible: int | None) -> tuple[list[str], str]:
    """Return (failures, variant_check_status).

    0458: base_eligible=1 → variant row MUST exist (absence is FAIL).
          base_eligible=0 → no variant expected; return not_expected.
          base_eligible=None → treat as eligible (fail-closed).
    """
    # NULL / absent defaults to eligible (fail-closed — 0458)
    if base_eligible == 0:
        return [], "not_expected"

    shadow_ep_row = conn.execute(
        """SELECT episode_id FROM model_observations
           WHERE decision_cohort_id=? AND model_version=? AND would_select=1 LIMIT 1""",
        (cohort_id, model_version),
    ).fetchone()
    variant_row = conn.execute(
        """SELECT challenger_episode_id FROM decision_variants
           WHERE decision_cohort_id=? AND challenger_model_version=? LIMIT 1""",
        (cohort_id, model_version),
    ).fetchone()

    # 0458: variant row must exist when base was eligible
    if variant_row is None:
        return (
            [f"decision_variants row missing for cohort={cohort_id} model={model_version} "
             f"(base_recommendation_eligible=1 — variant is required)"],
            "fail_missing_variant",
        )

    challenger_ep = _col(variant_row, "challenger_episode_id")
    if challenger_ep is None:
        return (
            ["decision_variants.challenger_episode_id is NULL"],
            "fail_null_episode",
        )

    shadow_ep = shadow_ep_row["episode_id"] if shadow_ep_row else None
    if shadow_ep != challenger_ep:
        return (
            [f"shadow episode {shadow_ep!r} != variant episode {challenger_ep!r}"],
            "fail_episode_mismatch",
        )

    return [], "pass"


def _run_integrity_audit(db_path: str) -> tuple[str, dict]:
    """Run check_integrity.py; return (overall, full_result).

    0457: returns ("error", ...) on any execution/parse failure so callers
    can treat it as non-healthy without special-casing.
    """
    try:
        env = {**__import__("os").environ, "INVESTMENT_DB": db_path}
        result = subprocess.run(
            [sys.executable, str(_REPO_ROOT / "check_integrity.py"), "--json"],
            capture_output=True, text=True, env=env,
        )
        data = json.loads(result.stdout)
        return data.get("overall", "error"), data
    except Exception as e:
        return "error", {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Top-level acceptance runners
# ─────────────────────────────────────────────────────────────────────────────

def run_shadow_acceptance(db_path: str, waive_integrity_warn: bool = False) -> dict:
    """Validate the observation pipeline after the first OBSERVE sweep."""
    conn = _connect(db_path)
    sweep = _find_shadow_sweep(conn)
    if sweep is None:
        conn.close()
        return {"status": "NO_SWEEP",
                "message": "No completed OBSERVE sweep found yet."}

    failures: list[str] = []
    checks: dict = {}

    # Sweep counts
    cf = _check_sweep_counts(sweep)
    checks["sweep_counts"] = {"failures": cf}
    failures.extend(f"[sweep_counts] {f}" for f in cf)

    agent_run_id = sweep.get("agent_run_id", "")
    cohort_id    = sweep.get("cohort_id", "")
    model_version = sweep.get("model_version", "")

    # Single cohort per run
    if agent_run_id:
        sf = _check_single_cohort_per_run(conn, agent_run_id)
        checks["single_cohort"] = {"failures": sf}
        failures.extend(f"[single_cohort] {f}" for f in sf)
    else:
        checks["single_cohort"] = {"failures": ["agent_run_id not set"]}
        failures.append("[single_cohort] agent_run_id not set on sweep row")

    # Winner counts
    wf = _check_winner_counts(conn, cohort_id, model_version)
    checks["winner_counts"] = {"failures": wf}
    failures.extend(f"[winners] {f}" for f in wf)

    # Observation → run mapping
    if agent_run_id:
        mf = _check_observation_run_mapping(conn, cohort_id, model_version, agent_run_id)
        checks["obs_run_mapping"] = {"failures": mf}
        failures.extend(f"[run_mapping] {f}" for f in mf)

    conn.close()

    # Integrity audit (0457: only "ok" is healthy; WARN fails unless waived)
    integrity_overall, integrity_result = _run_integrity_audit(db_path)
    checks["integrity"] = {"overall": integrity_overall}
    _integrity_ok = (
        integrity_overall in _HEALTHY_INTEGRITY
        or (waive_integrity_warn and integrity_overall == "WARN")
    )
    if not _integrity_ok:
        failures.append(f"[integrity] overall={integrity_overall!r} (must be 'ok')")

    return {
        "status": "PASS" if not failures else "FAIL",
        "mode": "shadow",
        "failures": failures,
        "checks": checks,
        "sweep": sweep,
        "integrity_overall": integrity_overall,
        "integrity_waived_warn": waive_integrity_warn and integrity_overall == "WARN",
    }


def run_paper_acceptance(db_path: str, waive_integrity_warn: bool = False) -> dict:
    """Validate the full learning-to-paper path after first base-eligible PAPER_ACTIVE sweep."""
    conn = _connect(db_path)
    sweep = _find_paper_sweep(conn)
    if sweep is None:
        conn.close()
        return {"status": "NO_SWEEP",
                "message": "No completed base-eligible PAPER_ACTIVE sweep found yet."}

    failures: list[str] = []
    checks: dict = {}

    # Sweep counts
    cf = _check_sweep_counts(sweep)
    checks["sweep_counts"] = {"failures": cf}
    failures.extend(f"[sweep_counts] {f}" for f in cf)

    agent_run_id  = sweep.get("agent_run_id", "")
    cohort_id     = sweep.get("cohort_id", "")
    model_version = sweep.get("model_version", "")
    base_eligible = sweep.get("base_recommendation_eligible")  # 0458

    # Single cohort per run
    if agent_run_id:
        sf = _check_single_cohort_per_run(conn, agent_run_id)
        checks["single_cohort"] = {"failures": sf}
        failures.extend(f"[single_cohort] {f}" for f in sf)
    else:
        checks["single_cohort"] = {"failures": ["agent_run_id not set"]}
        failures.append("[single_cohort] agent_run_id not set on sweep row")

    # Winner counts
    wf = _check_winner_counts(conn, cohort_id, model_version)
    checks["winner_counts"] = {"failures": wf}
    failures.extend(f"[winners] {f}" for f in wf)

    # Observation → run mapping
    if agent_run_id:
        mf = _check_observation_run_mapping(conn, cohort_id, model_version, agent_run_id)
        checks["obs_run_mapping"] = {"failures": mf}
        failures.extend(f"[run_mapping] {f}" for f in mf)

    # Paper variant agreement (0458: eligibility-aware)
    vf, vstatus = _check_paper_variant_agreement(conn, cohort_id, model_version, base_eligible)
    checks["paper_variant"] = {"status": vstatus, "failures": vf}
    failures.extend(f"[variant] {f}" for f in vf)

    conn.close()

    # Integrity audit
    integrity_overall, integrity_result = _run_integrity_audit(db_path)
    checks["integrity"] = {"overall": integrity_overall}
    _integrity_ok = (
        integrity_overall in _HEALTHY_INTEGRITY
        or (waive_integrity_warn and integrity_overall == "WARN")
    )
    if not _integrity_ok:
        failures.append(f"[integrity] overall={integrity_overall!r} (must be 'ok')")

    return {
        "status": "PASS" if not failures else "FAIL",
        "mode": "paper",
        "failures": failures,
        "checks": checks,
        "sweep": sweep,
        "integrity_overall": integrity_overall,
        "integrity_waived_warn": waive_integrity_warn and integrity_overall == "WARN",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Artifact builder
# ─────────────────────────────────────────────────────────────────────────────

def _build_artifact(result: dict, sha: str, dirty: bool) -> dict:
    sweep = result["sweep"]
    mode  = result["mode"]
    return {
        "_note": (
            "Append-only shadow-pipeline acceptance record (0455/0456). "
            "Validates OH → ledger → shadow scoring → episode lineage → winner counts. "
            "Observation pipeline verified — paper execution path not yet validated."
            if mode == "shadow" else
            "Append-only paper-execution acceptance record (0455/0456). "
            "Validates full learning-to-paper-decision path. "
            "Full architecture validated — architecture is now frozen."
        ),
        "mode": mode,
        "source_commit_sha": sha,
        "git_dirty": dirty,
        "agent_run_id": sweep.get("agent_run_id"),
        "cohort_id": sweep.get("cohort_id"),
        "model_version": sweep.get("model_version"),
        "phase": sweep.get("phase"),
        "expected_candidates": sweep.get("expected_candidates"),
        "scored_candidates": sweep.get("scored_candidates"),
        "base_recommendation_eligible": sweep.get("base_recommendation_eligible"),
        "canary_result": "PASS",
        "integrity_check_result": result["integrity_overall"],
        "integrity_warn_waived": result.get("integrity_waived_warn", False),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", default=str(_REPO_ROOT / "out" / "investment.db"))
    parser.add_argument("--mode", choices=["shadow", "paper"], default="shadow",
                        help="shadow: first OBSERVE sweep; paper: first base-eligible PAPER_ACTIVE sweep")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print result without writing the artifact")
    parser.add_argument("--waive-integrity-warn", action="store_true",
                        help="Allow integrity=WARN to pass (recorded in artifact)")
    args = parser.parse_args()

    run_fn  = run_shadow_acceptance if args.mode == "shadow" else run_paper_acceptance
    out_path = _SHADOW_OUT if args.mode == "shadow" else _PAPER_OUT

    result = run_fn(args.db, waive_integrity_warn=args.waive_integrity_warn)

    if result["status"] == "NO_SWEEP":
        print(f"\n[0455/{args.mode}] {result['message']}")
        print("Run this script again after the qualifying sweep has occurred.")
        sys.exit(2)

    sweep = result["sweep"]
    label = "Shadow pipeline" if args.mode == "shadow" else "Paper execution"
    print(f"\n=== {label} Acceptance (0455/0456) ===")
    print(f"  mode:          {args.mode}")
    print(f"  cohort_id:     {sweep.get('cohort_id')}")
    print(f"  agent_run_id:  {sweep.get('agent_run_id')}")
    print(f"  model_version: {sweep.get('model_version')}")
    print(f"  sweep status:  {sweep.get('status')}  "
          f"(expected={sweep.get('expected_candidates')} scored={sweep.get('scored_candidates')})")
    print(f"  integrity:     {result['integrity_overall']}")
    print(f"  result:        {result['status']}")

    if result["failures"]:
        print("\nFailures:")
        for f in result["failures"]:
            print(f"  FAIL  {f}")

    if result["status"] != "PASS":
        print(f"\n{label} acceptance FAILED — resolve the above before freezing.")
        sys.exit(1)

    # 0457: require clean git state before writing the permanent artifact
    sha   = _git_sha()
    dirty = _git_dirty()
    if sha is None:
        print("\nERROR: git SHA unavailable — cannot write authoritative acceptance record.")
        print("Ensure git is available and HEAD is set.")
        sys.exit(3)
    if dirty is True:
        print("\nERROR: worktree is dirty — commit all changes before writing acceptance record.")
        print("The source_commit_sha must unambiguously identify the running code.")
        sys.exit(3)

    record = _build_artifact(result, sha, dirty)

    if args.dry_run:
        print("\n[dry-run] Would write:")
        print(json.dumps(record, indent=2))
        return

    if out_path.exists():
        print(f"\nWARNING: {out_path} already exists — not overwriting.")
        print("This is an append-only record. Archive it if starting a new experiment.")
        sys.exit(1)

    out_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(f"\nAcceptance record written to {out_path}")
    if args.mode == "shadow":
        print("Observation pipeline verified. Paper execution path not yet validated.")
    else:
        print("Full architecture validated. Architecture is now frozen.")


if __name__ == "__main__":
    main()
