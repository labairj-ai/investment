# Parameterize Trainer with Explicit Horizon Version

- **ID:** 0379
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0372, 0373

## Problem

`train_and_save()` calls `ChallengerModel.train()` with no `horizon_version` argument, so it always defaults to `calendar_v1`. The sessions_v2 infrastructure built in 0372–0373 (parallel outcome labeling, version-aware observations, version-gated backfill) is never exercised by the normal scheduled trainer. Model provenance does not record which horizon the model was actually trained for, making the training target an accidental Python default rather than an explicit system configuration.

## Proposed approach

- Add `LEARNING_TARGET_HORIZON` (and optionally `LEARNING_TARGET_PERIOD`) constants to the config module; recommended default: `"sessions_v2"` / `"3m"` to match the 63-session paper portfolio horizon.
- Add `horizon_version: str = LEARNING_TARGET_HORIZON` parameter to `train_and_save()` and thread it through to `ChallengerModel.train(horizon_version=...)`.
- Persist the horizon version in the training run log / `learning_models` row so model provenance is explicit.
- Update the scheduled job (systemd timer script or CLI entry point) to explicitly pass the configured horizon rather than relying on the default.
- Open question: should training always use the config value, or should CLI allow a one-off override?

## Touches

- `agents/learning/calibration.py` — `train_and_save()` signature and body
- config module (wherever `LEARNING_TARGET_HORIZON` should live)
- systemd timer script / scheduled entry point
- `agent_db.py` if the `learning_models` schema needs a `training_horizon_version` column added (may already exist from 0373)
- `tests/test_calibration.py` — verify the horizon version is recorded and passed through

## Done when

- [ ] `LEARNING_TARGET_HORIZON` config constant exists and defaults to `"sessions_v2"`
- [ ] `train_and_save()` accepts and forwards `horizon_version` to `ChallengerModel.train()`
- [ ] The scheduled job explicitly sets the horizon rather than relying on a Python default
- [ ] `training_horizon_version` (or equivalent) is persisted in the run log / model row
- [ ] `python -m pytest tests/` passes with no regressions
