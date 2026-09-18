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
    """Score candidates using an OBSERVE/PAPER_ACTIVE/SUSPENDED model; write to model_observations.

    Does not affect live rankings. Builds the shadow prediction log for:
    - OBSERVE → PAPER_ACTIVE promotion gate (0360)
    - PAPER_ACTIVE degradation monitoring (0371/0374)
    - SUSPENDED retrospective audit (0371)

    0373: sets target_horizon_version from the model's training_horizon_version.
    0374: sets observation_phase from the model's current lifecycle_state.
    0378: sets baseline_predicted_alpha from model.mean_alpha; scored_at_date from today.
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

            # 0382: stable cohort id for all candidates scored in this run (UTC minute)
            decision_cohort_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")

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
                max_cs = max(o["ch_score"] for _, o in scored_pairs)
                # 0382: compute base_would_select — top quintile by base_score
                n_sp = len(scored_pairs)
                q_sz = max(1, n_sp // 5)
                base_scored = [(i, o["base_score"]) for i, (_, o) in enumerate(scored_pairs)
                               if o["base_score"] is not None]
                base_top_idxs: set = set()
                if base_scored:
                    top_base = sorted(base_scored, key=lambda x: x[1], reverse=True)[:q_sz]
                    base_top_idxs = {idx for idx, _ in top_base}

                for i, (c, out) in enumerate(scored_pairs):
                    ep_id = c.get("_episode_id")
                    if not ep_id:
                        continue
                    base_would_sel = None
                    if base_scored:
                        base_would_sel = 1 if i in base_top_idxs else 0
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
                             1 if out["ch_score"] == max_cs else 0,
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
