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


def score_for_observe(model_version: str, candidates: list, *, cohort_id: str) -> None:
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
    """
    import agent_db
    from datetime import datetime, timezone

    try:
        conn = agent_db._connect()
        try:
            row = conn.execute(
                "SELECT * FROM learning_models WHERE model_version=? AND lifecycle_state IN (?,?,?)",
                (model_version, LIFECYCLE_OBSERVE, LIFECYCLE_SUSPENDED, LIFECYCLE_PAPER_ACTIVE),
            ).fetchone()
            if not row:
                return

            model = ChallengerModel._from_row(row)
            if model is None:
                return

            observation_phase = row["lifecycle_state"]
            keys = row.keys() if hasattr(row, "keys") else []
            training_horizon_version = (row["training_horizon_version"]
                                        if "training_horizon_version" in keys else None) or "calendar_v1"

            now = datetime.now(timezone.utc).isoformat()
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
                predicted = model.predict_alpha(c)
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
                    try:
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
                    except Exception:
                        pass
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[challenger] WARNING: score_for_observe failed: {e}")


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
