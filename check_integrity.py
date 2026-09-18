"""Learning integrity audit — 0410.

Queries the live DB and reports on structural violations in the learning
pipeline. Run manually:

    python check_integrity.py [--db /path/to/agent.db] [--json]

Exit code: 0 = clean, 1 = warnings only, 2 = blocking violations found.
"""
from __future__ import annotations

import argparse
import json
import sys

import agent_db


# ── Checks ────────────────────────────────────────────────────────────────────

def _check_winner_violations(conn) -> dict:
    """SUM(would_select) != 1 or SUM(base_would_select) != 1 per cohort."""
    rows = conn.execute(
        """SELECT model_version, decision_cohort_id,
                  SUM(would_select)                    AS ch_winners,
                  SUM(COALESCE(base_would_select, 0))  AS base_winners
           FROM model_observations
           WHERE decision_cohort_id IS NOT NULL
           GROUP BY model_version, decision_cohort_id
           HAVING ch_winners != 1 OR base_winners != 1"""
    ).fetchall()
    return {
        "name": "winner_count_violations",
        "severity": "BLOCK",
        "count": len(rows),
        "detail": [
            {"model_version": r[0], "cohort_id": r[1],
             "ch_winners": r[2], "base_winners": r[3]}
            for r in rows
        ],
        "status": "BLOCK" if rows else "ok",
    }


def _check_horizon_contamination(conn) -> dict:
    """sessions_v2 model_observations with NULL target_horizon_version."""
    rows = conn.execute(
        """SELECT mo.model_version, COUNT(*) AS n
           FROM model_observations mo
           JOIN learning_models lm ON mo.model_version = lm.model_version
           WHERE lm.training_horizon_version = 'sessions_v2'
             AND (mo.target_horizon_version IS NULL
                  OR mo.target_horizon_version != 'sessions_v2')
           GROUP BY mo.model_version"""
    ).fetchall()
    return {
        "name": "horizon_contamination",
        "severity": "WARN",
        "count": sum(r[1] for r in rows),
        "detail": [{"model_version": r[0], "n_contaminated": r[1]} for r in rows],
        "status": "WARN" if rows else "ok",
    }


def _check_orphan_observations(conn) -> dict:
    """model_observations whose episode_id has no row in decision_episodes."""
    rows = conn.execute(
        """SELECT mo.model_version, COUNT(*) AS n
           FROM model_observations mo
           LEFT JOIN decision_episodes de ON mo.episode_id = de.episode_id
           WHERE de.episode_id IS NULL
           GROUP BY mo.model_version"""
    ).fetchall()
    return {
        "name": "orphan_observations",
        "severity": "WARN",
        "count": sum(r[1] for r in rows),
        "detail": [{"model_version": r[0], "n_orphans": r[1]} for r in rows],
        "status": "WARN" if rows else "ok",
    }


def _check_unlabeled_mature(conn) -> dict:
    """PAPER_ACTIVE observations past their 63-session maturity with no outcome."""
    from datetime import date, timedelta
    from trade_engine.market_calendar import nth_trading_session_before, is_trading_day

    today = date.today().isoformat()
    # Cutoff: episodes captured on or before this date should have 63 sessions elapsed
    try:
        cutoff = nth_trading_session_before(today, 63)
    except Exception:
        cutoff = (date.today() - timedelta(days=95)).isoformat()

    rows = conn.execute(
        """SELECT COUNT(*) FROM model_observations
           WHERE outcome_alpha_90d IS NULL
             AND (observation_phase = 'PAPER_ACTIVE' OR observation_phase IS NULL)
             AND scored_at_date IS NOT NULL
             AND scored_at_date <= ?""",
        (cutoff,),
    ).fetchone()
    n = rows[0] if rows else 0
    return {
        "name": "unlabeled_mature_obs",
        "severity": "WARN",
        "count": n,
        "detail": {"sessions_cutoff": cutoff},
        "status": "WARN" if n > 0 else "ok",
    }


def _check_paper_active_horizon(conn) -> dict:
    """PAPER_ACTIVE model trained on a horizon that differs from sessions_v2."""
    rows = conn.execute(
        """SELECT model_version, training_horizon_version, lifecycle_state
           FROM learning_models
           WHERE lifecycle_state = 'PAPER_ACTIVE'"""
    ).fetchall()
    wrong = [r for r in rows if r[1] not in ("sessions_v2",)]
    return {
        "name": "paper_active_wrong_horizon",
        "severity": "BLOCK",
        "count": len(wrong),
        "detail": [
            {"model_version": r[0], "training_horizon_version": r[1]}
            for r in wrong
        ],
        "status": "BLOCK" if wrong else "ok",
    }


def _check_shadow_paper_disagreement(conn) -> dict:
    """Cohort dates where shadow would_select episode != paper recommended episode.

    Joins model_observations (shadow) with decision_episodes (paper actuals).
    A mismatch means the live ranking and scoring differed at execution time —
    potentially because rounding or the selection function diverged (0404).
    """
    rows = conn.execute(
        """SELECT mo.decision_cohort_id, mo.scored_at_date, mo.episode_id AS shadow_ep,
                  de.episode_id AS paper_ep, de.selected
           FROM model_observations mo
           JOIN decision_episodes de
             ON mo.scored_at_date = DATE(de.captured_at, 'unixepoch')
           WHERE mo.would_select = 1
             AND de.selected = 1
             AND mo.episode_id != de.episode_id
             AND mo.observation_phase IN ('PAPER_ACTIVE')
           ORDER BY mo.scored_at_date DESC
           LIMIT 50"""
    ).fetchall()
    return {
        "name": "shadow_paper_disagreement",
        "severity": "BLOCK",
        "count": len(rows),
        "detail": [
            {"cohort_id": r[0], "date": r[1],
             "shadow_ep": r[2], "paper_ep": r[3]}
            for r in rows
        ],
        "status": "BLOCK" if rows else "ok",
    }


def _check_null_cohort_obs(conn) -> dict:
    """PAPER_ACTIVE observations that were written without a decision_cohort_id."""
    row = conn.execute(
        """SELECT COUNT(*) FROM model_observations
           WHERE decision_cohort_id IS NULL
             AND observation_phase = 'PAPER_ACTIVE'"""
    ).fetchone()
    n = row[0] if row else 0
    return {
        "name": "null_cohort_paper_obs",
        "severity": "WARN",
        "count": n,
        "detail": {},
        "status": "WARN" if n > 0 else "ok",
    }


# ── Runner ────────────────────────────────────────────────────────────────────

_CHECKS = [
    _check_winner_violations,
    _check_horizon_contamination,
    _check_orphan_observations,
    _check_unlabeled_mature,
    _check_paper_active_horizon,
    _check_shadow_paper_disagreement,
    _check_null_cohort_obs,
]


def run_integrity_audit(conn=None) -> dict:
    """Run all integrity checks; return structured result dict."""
    close = False
    if conn is None:
        conn = agent_db._connect()
        close = True
    try:
        results = []
        for fn in _CHECKS:
            try:
                results.append(fn(conn))
            except Exception as exc:
                results.append({
                    "name": fn.__name__,
                    "severity": "WARN",
                    "count": -1,
                    "detail": {"error": str(exc)},
                    "status": "error",
                })
        blocks = [r for r in results if r["status"] == "BLOCK"]
        warns  = [r for r in results if r["status"] == "WARN"]
        overall = "BLOCK" if blocks else ("WARN" if warns else "ok")
        return {"overall": overall, "checks": results}
    finally:
        if close:
            conn.close()


def _fmt_check(c: dict) -> str:
    sev_icon = {"ok": "OK  ", "WARN": "WARN", "BLOCK": "BLOK", "error": "ERR "}.get(c["status"], "??? ")
    return f"  [{sev_icon}] {c['name']}: {c['count']} issue(s)"


def main() -> None:
    ap = argparse.ArgumentParser(description="Investment learning integrity audit (0410)")
    ap.add_argument("--json", action="store_true", help="Output JSON instead of human-readable text")
    args = ap.parse_args()

    result = run_integrity_audit()

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        overall = result["overall"]
        print(f"\nLearning Integrity Audit — overall: {overall}\n")
        for c in result["checks"]:
            print(_fmt_check(c))
            if c["count"] not in (0, -1) and c["detail"]:
                detail = c["detail"]
                if isinstance(detail, list):
                    for item in detail[:5]:
                        print(f"       {item}")
                    if len(detail) > 5:
                        print(f"       ... and {len(detail) - 5} more")
                else:
                    print(f"       {detail}")
        print()

    blocks = [c for c in result["checks"] if c["status"] == "BLOCK"]
    warns  = [c for c in result["checks"] if c["status"] == "WARN"]
    sys.exit(2 if blocks else (1 if warns else 0))


if __name__ == "__main__":
    main()
