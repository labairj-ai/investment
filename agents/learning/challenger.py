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

from .calibration import ChallengerModel

_cached_model: ChallengerModel | None = None
_cached_version: str | None = None


def get_model() -> ChallengerModel | None:
    """Return the latest active challenger model, or None if unavailable/inactive."""
    global _cached_model, _cached_version
    try:
        model = ChallengerModel.load_latest()
        if model is None:
            return None
        if model.model_version != _cached_version:
            _cached_model = model
            _cached_version = model.model_version
        return _cached_model if (_cached_model and _cached_model.training_n >= 30) else None
    except Exception as e:
        print(f"[challenger] WARNING: failed to load model: {e}")
        return None


def apply_challenger_adjustment(candidate: dict) -> tuple[int, dict]:
    """Return (adjusted_composite, challenger_info) for a scored candidate.

    challenger_info contains the scoring metadata (or {"active": False} if no model).
    The returned composite is clamped to [0, 100].
    """
    model = get_model()
    if model is None:
        return candidate["_composite"], {"active": False}

    info = model.score(candidate)
    adj  = info.get("learning_adjustment", 0.0)
    new_composite = int(round(max(0.0, min(100.0, candidate["_composite"] + adj))))
    return new_composite, info
