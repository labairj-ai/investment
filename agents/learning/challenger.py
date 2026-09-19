"""Challenger model loader — applies bounded learning adjustment to candidates (0330).

Called from opportunity_agent.run_opportunity_hunter() after base scoring.
The adjustment is applied only when:
  - A trained model exists in learning_models (persisted by calibration.train_and_save())
  - model.training_n >= MIN_TRAINING_N
  - The candidate has all five component features

When active, the effective score is:
    S_effective = S_base + clip(learning_adjustment, -MAX_ADJUSTMENT, +MAX_ADJUSTMENT)

Hard risk limits in the risk engine are unaffected.
"""
from __future__ import annotations

from .calibration import ChallengerModel, LIFECYCLE_PAPER_ACTIVE, LIFECYCLE_OBSERVE, LIFECYCLE_SUSPENDED

_cached_model: ChallengerModel | None = None
_cached_version: str | None = None


def get_model() -> ChallengerModel | None:
    """Return the PAPER_ACTIVE challenger model, or None (0335/0344).

    Uses load_paper_active() so a newly trained (TRAINED/OBSERVE) model never
    shadows the incumbent PAPER_ACTIVE model.  Models in TRAINED or OBSERVE state
    have no influence on scoring until explicitly promoted via calibration.promote().
    """
    global _cached_model, _cached_version
    try:
        model = ChallengerModel.load_paper_active()
        if model is None:
            _cached_model = None
            _cached_version = None
            return None
        if model.model_version != _cached_version:
            _cached_model = model
            _cached_version = model.model_version
        return _cached_model
    except Exception as e:
        print(f"[challenger] WARNING: failed to load model: {e}")
        return None


def score_for_observe(
    model_version: str,
    candidates: list,
    *,
    cohort_id: str,
    base_recommendation_eligible: bool | None = None,
    agent_run_id: str,
) -> None:
    """Score candidates using an OBSERVE/PAPER_ACTIVE/SUSPENDED model; write to model_observations.

    Does not affect live rankings. Builds the shadow prediction log for:
    - OBSERVE → PAPER_ACTIVE promotion gate (0360)
    - PAPER_ACTIVE degradation monitoring (0371/0374)
    - SUSPENDED retrospective audit (0371)

    0373: sets target_horizon_version from the model's training_horizon_version.
    0374: sets observation_phase from the model's current lifecycle_state.
    0378: sets baseline_predicted_alpha from model.mean_alpha; scored_at_date from today.
    0398: cohort_id is mandatory (keyword-only). Callers must generate one UUID per sweep
          and pass it here so all models in one run share a single decision_cohort_id.
    0406: cohort_id is no longer optional; omitting it raises TypeError at call time.
    0419: base_recommendation_eligible records whether the base strategy would have acted
          on this sweep (top composite >= threshold). Stored in sweep ledger for population
          analysis — does NOT gate shadow scoring.
    0424: agent_run_id ties the ledger row back to the triggering OH invocation.
          Ledger INSERT failure is now fail-closed: raises so the caller can log and abort
          shadow scoring. The base recommendation path is unaffected (caller catches).
    0425: scored_candidates is set from actual COUNT(*) after inserts, not attempted-insert
          counter. status=PARTIAL when actual < expected (no error). completed_at is full ISO.
    """
    # 0434: agent_run_id is mandatory — a missing run_id means the sweep cannot be audited
    if not agent_run_id:
        raise ValueError(
            f"[challenger] agent_run_id is required for model {model_version} cohort={cohort_id}"
        )

    import agent_db
    from datetime import datetime, timezone

    conn = agent_db._connect()
    # 0418/0419/0424: write sweep ledger row BEFORE scoring — fail-closed on failure
    now = datetime.now(timezone.utc).isoformat()
    eligible_int = (1 if base_recommendation_eligible else 0) if base_recommendation_eligible is not None else None
    sweep_row_id: int | None = None
    try:
        cur = conn.execute(
            """INSERT INTO learning_sweep_runs
               (cohort_id, model_version, agent_run_id, phase, expected_candidates,
                scored_candidates, base_recommendation_eligible, started_at, status)
               VALUES (?,?,?,?,?,0,?,?,'STARTED')""",
            (cohort_id, model_version, agent_run_id, None, len(candidates), eligible_int, now),
        )
        sweep_row_id = cur.lastrowid
        conn.commit()
    except Exception as _ledger_err:
        conn.close()
        # 0424: ledger write failure aborts shadow scoring — learning observations must
        # not exist without a corresponding STARTED ledger row.
        raise RuntimeError(
            f"[challenger] sweep ledger INSERT failed for {model_version} cohort={cohort_id}: "
            f"{_ledger_err}"
        ) from _ledger_err

    try:
        row = conn.execute(
            "SELECT * FROM learning_models WHERE model_version=? AND lifecycle_state IN (?,?,?)",
            (model_version, LIFECYCLE_OBSERVE, LIFECYCLE_SUSPENDED, LIFECYCLE_PAPER_ACTIVE),
        ).fetchone()
        if not row:
            if sweep_row_id is not None:
                conn.execute(
                    "UPDATE learning_sweep_runs SET status='SKIPPED',completed_at=? WHERE id=?",
                    (now, sweep_row_id),
                )
                conn.commit()
            return

        model = ChallengerModel._from_row(row)
        if model is None:
            if sweep_row_id is not None:
                conn.execute(
                    "UPDATE learning_sweep_runs SET status='SKIPPED',completed_at=? WHERE id=?",
                    (now, sweep_row_id),
                )
                conn.commit()
            return

        observation_phase = row["lifecycle_state"]
        # Update phase in ledger now that we know it
        if sweep_row_id is not None:
            try:
                conn.execute(
                    "UPDATE learning_sweep_runs SET phase=? WHERE id=?",
                    (observation_phase, sweep_row_id),
                )
                conn.commit()
            except Exception:
                pass

        keys = row.keys() if hasattr(row, "keys") else []
        training_horizon_version = (row["training_horizon_version"]
                                    if "training_horizon_version" in keys else None) or "calendar_v1"

        # 0384: use America/New_York date so evening runs don't advance to next UTC day
        # Fallback uses a fixed UTC-5 offset (EST) — avoids tzdata dependency on minimal systems
        try:
            from zoneinfo import ZoneInfo
            scored_at_date = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
        except Exception:
            from datetime import timezone as _tz, timedelta as _tdt
            scored_at_date = datetime.now(_tz(offset=_tdt(hours=-5))).strftime("%Y-%m-%d")

        decision_cohort_id = cohort_id

        scored_pairs: list[tuple] = []
        for c in candidates:
            predicted = model.predict_alpha(c)  # 0411/0422: adapter resolves _q/_v/... with alias priority
            if predicted is None:
                continue
            from .calibration import ALPHA_TO_SCORE_SCALE, MAX_ADJUSTMENT
            import numpy as np
            raw_adj = (predicted - model.mean_alpha) * ALPHA_TO_SCORE_SCALE
            adj = float(np.clip(model.reliability * raw_adj, -MAX_ADJUSTMENT, MAX_ADJUSTMENT))
            ch_score = float(c.get("composite_score") or c.get("_composite") or 0) + adj
            base_s = c.get("composite_score") or c.get("_composite")
            scored_pairs.append((c, {"predicted_alpha": predicted, "adjustment": adj,
                                     "ch_score": ch_score, "base_score": base_s}))

        n_written = 0
        if scored_pairs:
            # 0399: exactly one base top-1 and one challenger top-1 per cohort.
            # Tie-break deterministically: ch_score DESC, base_score DESC, ticker ASC.
            ch_top_idx = sorted(
                range(len(scored_pairs)),
                key=lambda i: (
                    -scored_pairs[i][1]["ch_score"],
                    -(scored_pairs[i][1]["base_score"] or 0.0),
                    scored_pairs[i][0].get("ticker", ""),
                ),
            )[0]

            # 0386: base_would_select = 1 for exactly top-1 by base_score; tie-break by ticker ASC
            base_scores_available = [i for i, (_, o) in enumerate(scored_pairs)
                                     if o["base_score"] is not None]
            base_top_idx: int = -1
            if base_scores_available:
                base_top_idx = sorted(
                    base_scores_available,
                    key=lambda i: (
                        -(scored_pairs[i][1]["base_score"] or 0.0),
                        scored_pairs[i][0].get("ticker", ""),
                    ),
                )[0]

            for i, (c, out) in enumerate(scored_pairs):
                ep_id = c.get("_episode_id")
                if not ep_id:
                    continue
                base_would_sel = None
                if base_scores_available:
                    base_would_sel = 1 if i == base_top_idx else 0
                conn.execute(
                    """INSERT OR IGNORE INTO model_observations
                       (model_version, episode_id, ticker, prediction_timestamp,
                        base_score, predicted_alpha, learning_adjustment,
                        challenger_score, would_select,
                        observation_phase, target_horizon_version,
                        baseline_predicted_alpha, scored_at_date,
                        decision_cohort_id, base_would_select)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (model_version, ep_id, c.get("ticker", ""),
                     now,
                     out["base_score"],
                     out["predicted_alpha"],
                     out["adjustment"],
                     out["ch_score"],
                     1 if i == ch_top_idx else 0,
                     observation_phase,
                     training_horizon_version,
                     model.mean_alpha,
                     scored_at_date,
                     decision_cohort_id,
                     base_would_sel),
                )
                n_written += 1
            conn.commit()

        # 0415: record successful shadow score timestamp so health check can detect stale learners
        if n_written > 0:
            conn.execute(
                """UPDATE learning_models
                   SET last_shadow_score_at=?, last_shadow_cohort_id=?
                   WHERE model_version=?""",
                (scored_at_date, decision_cohort_id, model_version),
            )
            conn.commit()

        # 0425/0431: COUNT(*) is authoritative; failure is fatal (fail-closed, not trusted-write)
        try:
            actual_count: int = conn.execute(
                "SELECT COUNT(*) FROM model_observations WHERE model_version=? AND decision_cohort_id=?",
                (model_version, cohort_id),
            ).fetchone()[0]
        except Exception as _cnt_err:
            if sweep_row_id is not None:
                try:
                    _now_cnt = datetime.now(timezone.utc).isoformat()
                    conn.execute(
                        "UPDATE learning_sweep_runs SET status='FAILED',error=?,completed_at=? WHERE id=?",
                        (f"count_query_failed: {_cnt_err}"[:500], _now_cnt, sweep_row_id),
                    )
                    conn.commit()
                except Exception:
                    pass
            raise RuntimeError(
                f"[challenger] post-insert COUNT failed for {model_version} cohort={cohort_id}: {_cnt_err}"
            ) from _cnt_err

        # 0418/0425: mark sweep COMPLETED or PARTIAL; use full ISO timestamp for completed_at
        _is_overcount = actual_count > len(candidates)
        if sweep_row_id is not None:
            try:
                now_complete = datetime.now(timezone.utc).isoformat()
                if actual_count == len(candidates):
                    final_status = "COMPLETED"
                elif actual_count < len(candidates):
                    final_status = "PARTIAL"
                else:
                    # 0431/0441: actual > expected is a structural integrity error
                    final_status = "FAILED"
                conn.execute(
                    """UPDATE learning_sweep_runs
                       SET scored_candidates=?, completed_at=?, status=?
                       WHERE id=?""",
                    (actual_count, now_complete, final_status, sweep_row_id),
                )
                conn.commit()
            except Exception:
                pass
        # 0441: raise AFTER persisting FAILED so the record is durable before unwinding
        if _is_overcount:
            from agents.learning.calibration import LearningIntegrityError
            raise LearningIntegrityError(
                f"[challenger] overcount for {model_version} cohort={cohort_id}: "
                f"actual={actual_count} > expected={len(candidates)}"
            )

    except Exception as e:
        # 0415: log at ERROR level — silent pass previously hid full scoring failures
        import logging as _log
        _log.getLogger(__name__).error(
            "[challenger] score_for_observe failed for %s cohort=%s: %s",
            model_version, cohort_id, e, exc_info=True,
        )
        print(f"[challenger] ERROR: score_for_observe failed ({model_version}): {e}")
        # 0418/0425: record failure in sweep ledger with full ISO timestamp
        if sweep_row_id is not None:
            try:
                now_fail = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE learning_sweep_runs SET status='FAILED',error=?,completed_at=? WHERE id=?",
                    (str(e)[:500], now_fail, sweep_row_id),
                )
                conn.commit()
            except Exception:
                pass
        raise
    finally:
        conn.close()


def apply_challenger_adjustment(candidate: dict) -> tuple[int, dict]:
    """Return (adjusted_composite_rounded, challenger_info) for a scored candidate.

    challenger_info contains the scoring metadata (or {"active": False} if no model).
    The returned composite is rounded to int for display/storage; use
    challenger_info["challenger_score_raw"] for ranking (0404).
    SUSPENDED models return 0.0 adjustment (0371) — shadow obs still written by score_for_observe().
    """
    import agent_db

    model = get_model()
    if model is None:
        # 0371: check if there is a SUSPENDED model — if so, report it but apply 0.0 adj
        try:
            conn = agent_db._connect()
            susp = conn.execute(
                "SELECT model_version FROM learning_models WHERE lifecycle_state=? LIMIT 1",
                (LIFECYCLE_SUSPENDED,),
            ).fetchone()
            conn.close()
            if susp:
                return (candidate["_composite"],
                        {"active": False, "suspended": True,
                         "model_version": susp["model_version"],
                         "challenger_score_raw": float(candidate["_composite"])})
        except Exception:
            pass
        return candidate["_composite"], {"active": False,
                                          "challenger_score_raw": float(candidate["_composite"])}

    info = model.score(candidate)
    adj  = info.get("learning_adjustment", 0.0)
    raw  = float(candidate["_composite"]) + adj
    info["challenger_score_raw"] = raw
    new_composite = int(round(max(0.0, min(100.0, raw))))
    return new_composite, info


def select_challenger_winner(scored: list) -> "dict | None":
    """Return the single challenger-top-1 candidate using the canonical tie-breaking policy.

    Tie-breaking: challenger_score_raw DESC → base _composite DESC → ticker ASC.
    Uses raw floating-point challenger scores so rounding never changes the winner (0404).
    Returns None if scored is empty.
    """
    if not scored:
        return None
    return sorted(
        scored,
        key=lambda c: (
            -(c.get("_challenger_info", {}).get("challenger_score_raw")
              or c.get("_composite_challenger", 0)),
            -(c.get("_composite") or 0),
            c.get("ticker", ""),
        ),
    )[0]


def select_base_winner(scored: list) -> "dict | None":
    """Return the single base-top-1 candidate using canonical tie-breaking.

    Tie-breaking: _composite DESC → ticker ASC (0404).
    Returns None if scored is empty.
    """
    if not scored:
        return None
    return sorted(
        scored,
        key=lambda c: (-(c.get("_composite") or 0), c.get("ticker", "")),
    )[0]
