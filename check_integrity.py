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
    """Shadow challenger episode != paper challenger episode for the same cohort.

    0412: Joins on decision_cohort_id (not calendar date) and compares
    model_observations.episode_id against decision_variants.challenger_episode_id.
    This avoids false positives when the challenger overrides the LLM selection
    (decision_episodes.selected=1 is the LLM pick, not the paper challenger's).
    Falls back to a WARN if decision_variants.decision_cohort_id is not yet populated.
    """
    try:
        rows = conn.execute(
            """SELECT mo.decision_cohort_id,
                      mo.scored_at_date,
                      mo.episode_id         AS shadow_ep,
                      dv.challenger_episode_id AS paper_ep,
                      mo.model_version
               FROM model_observations mo
               JOIN decision_variants dv
                 ON mo.decision_cohort_id = dv.decision_cohort_id
                AND mo.model_version = dv.challenger_model_version
               WHERE mo.would_select = 1
                 AND mo.observation_phase = 'PAPER_ACTIVE'
                 AND dv.challenger_episode_id IS NOT NULL
                 AND mo.episode_id != dv.challenger_episode_id
               ORDER BY mo.scored_at_date DESC
               LIMIT 50"""
        ).fetchall()
        # Check whether any cohorts have been linked (if 0 variants have cohort_id yet, return WARN)
        linked_count = conn.execute(
            "SELECT COUNT(*) FROM decision_variants WHERE decision_cohort_id IS NOT NULL"
        ).fetchone()[0]
        if linked_count == 0:
            return {
                "name": "shadow_paper_disagreement",
                "severity": "WARN",
                "count": 0,
                "detail": {"note": "No decision_variants have decision_cohort_id yet (0412 not yet deployed to live data)"},
                "status": "WARN",
            }
        return {
            "name": "shadow_paper_disagreement",
            "severity": "BLOCK",
            "count": len(rows),
            "detail": [
                {"cohort_id": r[0], "date": r[1], "shadow_ep": r[2], "paper_ep": r[3],
                 "model_version": r[4]}
                for r in rows
            ],
            "status": "BLOCK" if rows else "ok",
        }
    except Exception as exc:
        return {
            "name": "shadow_paper_disagreement",
            "severity": "WARN",
            "count": -1,
            "detail": {"error": str(exc)},
            "status": "error",
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


def _check_candidate_coverage(conn) -> dict:
    """Every scoring sweep must have observations equal to expected_candidates.

    0418: Uses learning_sweep_runs (written BEFORE scoring) as the source of truth
    so zero-row cohorts are detectable — they appear in the ledger even when
    model_observations is empty.  Covers OBSERVE, PAPER_ACTIVE, and SUSPENDED phases.

    0413 (previous): The old SQL started from model_observations (inner join) so a
    sweep that scored 0 candidates was completely invisible.  This version inverts the
    join direction, starting from the ledger.

    Falls back to WARN + old inner-join logic when learning_sweep_runs doesn't exist yet.
    """
    try:
        # Check that the sweep ledger table exists (0418 migration required)
        tbl_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='learning_sweep_runs'"
        ).fetchone()
        if not tbl_exists:
            return {
                "name": "candidate_coverage",
                "severity": "WARN",
                "count": 0,
                "detail": {"note": "learning_sweep_runs table not found — 0418 migration pending"},
                "status": "WARN",
            }

        # LEFT JOIN: every ledger row is considered; rows without matching observations
        # are the ones that scored zero or fewer than expected.
        # 0425: PARTIAL status (actual < expected, no error) is also a coverage gap.
        problem_rows = conn.execute(
            """SELECT sr.cohort_id,
                      sr.model_version,
                      sr.phase,
                      sr.expected_candidates,
                      COALESCE(sr.scored_candidates, 0)  AS scored_candidates,
                      sr.status,
                      sr.error
               FROM learning_sweep_runs sr
               WHERE sr.status IN ('COMPLETED', 'FAILED', 'STARTED', 'PARTIAL')
                 AND (
                     sr.status IN ('FAILED', 'PARTIAL')
                     OR COALESCE(sr.scored_candidates, 0) != sr.expected_candidates
                 )
               ORDER BY sr.started_at DESC
               LIMIT 50"""
        ).fetchall()
        return {
            "name": "candidate_coverage",
            "severity": "BLOCK",
            "count": len(problem_rows),
            "detail": [
                {
                    "cohort_id": r["cohort_id"],
                    "model_version": r["model_version"],
                    "phase": r["phase"],
                    "expected": r["expected_candidates"],
                    "scored": r["scored_candidates"],
                    "status": r["status"],
                    "error": r["error"],
                }
                for r in problem_rows
            ],
            "status": "BLOCK" if problem_rows else "ok",
        }
    except Exception as exc:
        return {
            "name": "candidate_coverage",
            "severity": "WARN",
            "count": -1,
            "detail": {"error": str(exc)},
            "status": "error",
        }


def _check_ledger_observation_consistency(conn) -> dict:
    """For each OBSERVE/PAPER_ACTIVE/SUSPENDED model, verify cohorts have COMPLETED ledger rows.

    0429: PARTIAL/FAILED ledger rows are BLOCK — those cohorts' observations are excluded from
    promotion/degradation gate calculations.  Pre-0424 cohorts with no ledger row at all are
    treated as legacy (WARN, not BLOCK) until they age out of the evaluation window.
    """
    try:
        tbl_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='learning_sweep_runs'"
        ).fetchone()
        if not tbl_exists:
            return {
                "name": "ledger_observation_consistency",
                "severity": "WARN",
                "count": 0,
                "detail": {"note": "learning_sweep_runs table not found — 0424 migration pending"},
                "status": "WARN",
            }

        cohort_rows = conn.execute(
            """SELECT DISTINCT mo.model_version, mo.decision_cohort_id
               FROM model_observations mo
               JOIN learning_models lm ON mo.model_version = lm.model_version
               WHERE lm.lifecycle_state IN ('OBSERVE','PAPER_ACTIVE','SUSPENDED')
                 AND mo.decision_cohort_id IS NOT NULL"""
        ).fetchall()

        if not cohort_rows:
            return {
                "name": "ledger_observation_consistency",
                "severity": "ok",
                "count": 0,
                "detail": [],
                "status": "ok",
            }

        partial_or_failed = []
        no_ledger = []
        for cr in cohort_rows:
            mv = cr["model_version"]
            cid = cr["decision_cohort_id"]
            ledger = conn.execute(
                """SELECT status FROM learning_sweep_runs
                   WHERE cohort_id=? AND model_version=?
                   ORDER BY id DESC LIMIT 1""",
                (cid, mv),
            ).fetchone()
            if ledger is None:
                no_ledger.append({"model_version": mv, "cohort_id": cid})
            elif ledger["status"] in ("PARTIAL", "FAILED"):
                partial_or_failed.append(
                    {"model_version": mv, "cohort_id": cid, "status": ledger["status"]}
                )

        if partial_or_failed:
            return {
                "name": "ledger_observation_consistency",
                "severity": "BLOCK",
                "count": len(partial_or_failed),
                "detail": partial_or_failed[:20],
                "no_ledger_legacy_count": len(no_ledger),
                "status": "BLOCK",
            }
        elif no_ledger:
            return {
                "name": "ledger_observation_consistency",
                "severity": "WARN",
                "count": len(no_ledger),
                "detail": no_ledger[:20],
                "status": "WARN",
            }
        else:
            return {
                "name": "ledger_observation_consistency",
                "severity": "ok",
                "count": 0,
                "detail": [],
                "status": "ok",
            }
    except Exception as exc:
        return {
            "name": "ledger_observation_consistency",
            "severity": "WARN",
            "count": -1,
            "detail": {"error": str(exc)},
            "status": "error",
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
    _check_candidate_coverage,
    _check_ledger_observation_consistency,
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
        errors = [r for r in results if r["status"] == "error"]
        warns  = [r for r in results if r["status"] == "WARN"]
        overall = "BLOCK" if blocks else ("error" if errors else ("WARN" if warns else "ok"))
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
    errors = [c for c in result["checks"] if c["status"] == "error"]
    warns  = [c for c in result["checks"] if c["status"] == "WARN"]
    sys.exit(2 if blocks else (1 if errors or warns else 0))


if __name__ == "__main__":
    main()
