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


def score_for_observe(model_version: str, candidates: list[dict]) -> None:
    """Score candidates using an OBSERVE-state model; write to model_observations (0360).

    Does not affect rankings. Builds the shadow prediction log that the
    OBSERVE→PAPER_ACTIVE gate (mature_observations) checks against.
    SUSPENDED models also write observations for retrospective audit (0371).
    """
    import agent_db
    from datetime import datetime, timezone

    try:
        conn = agent_db._connect()
        try:
            row = conn.execute(
                "SELECT * FROM learning_models WHERE model_version=? AND lifecycle_state IN (?,?)",
                (model_version, LIFECYCLE_OBSERVE, LIFECYCLE_SUSPENDED),
            ).fetchone()
            if not row:
                return

            model = ChallengerModel._from_row(row)
            if model is None:
                return

            now = datetime.now(timezone.utc).isoformat()
            scored_pairs: list[tuple] = []
            for c in candidates:
                # Use predict_alpha directly — score() only activates for PAPER_ACTIVE
                predicted = model.predict_alpha(c)
                if predicted is None:
                    continue
                # Compute adjustment using same formula as score()
                from .calibration import ALPHA_TO_SCORE_SCALE, MAX_ADJUSTMENT
                import numpy as np
                raw_adj = (predicted - model.mean_alpha) * ALPHA_TO_SCORE_SCALE
                adj = float(np.clip(model.reliability * raw_adj, -MAX_ADJUSTMENT, MAX_ADJUSTMENT))
                ch_score = float(c.get("composite_score") or c.get("_composite") or 0) + adj
                scored_pairs.append((c, {"predicted_alpha": predicted, "adjustment": adj, "ch_score": ch_score}))

            if scored_pairs:
                max_cs = max(o["ch_score"] for _, o in scored_pairs)
                for c, out in scored_pairs:
                    ep_id = c.get("_episode_id")
                    if not ep_id:
                        continue
                    try:
                        conn.execute(
                            """INSERT OR IGNORE INTO model_observations
                               (model_version, episode_id, ticker, prediction_timestamp,
                                base_score, predicted_alpha, learning_adjustment,
                                challenger_score, would_select)
                               VALUES (?,?,?,?,?,?,?,?,?)""",
                            (model_version, ep_id, c.get("ticker", ""),
                             now,
                             c.get("composite_score") or c.get("_composite"),
                             out["predicted_alpha"],
                             out["adjustment"],
                             out["ch_score"],
                             1 if out["ch_score"] == max_cs else 0),
                        )
                    except Exception:
                        pass
                conn.commit()
        finally:
            conn.close()
    except Exception as e:
        print(f"[challenger] WARNING: score_for_observe failed: {e}")


def apply_challenger_adjustment(candidate: dict) -> tuple[int, dict]:
    """Return (adjusted_composite, challenger_info) for a scored candidate.

    challenger_info contains the scoring metadata (or {"active": False} if no model).
    The returned composite is clamped to [0, 100].
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
                return candidate["_composite"], {"active": False, "suspended": True,
                                                  "model_version": susp["model_version"]}
        except Exception:
            pass
        return candidate["_composite"], {"active": False}

    info = model.score(candidate)
    adj  = info.get("learning_adjustment", 0.0)
    new_composite = int(round(max(0.0, min(100.0, candidate["_composite"] + adj))))
    return new_composite, info
