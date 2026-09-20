# UUID-Based Model Identity with Config and Commit Hash

- **ID:** 0416
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0409

## Problem

The current model version string (`edge_{horizon}_{schema_hash[:8]}_v{cutoff}`) encodes only the feature schema and training cutoff. It does not distinguish models trained with different `RIDGE_ALPHA`, shrinkage lambda, alpha-to-score scale, max adjustment, outcome horizon period, training exclusions, CV algorithm version, or code commit. Two materially different models trained on the same features and cutoff produce the same version key, which means a retrain after a hyperparameter change silently overwrites the prior model's identity.

## Proposed approach

- Assign a UUID `model_id` as the immutable primary key; keep `model_version` as a human-readable display name only.
- Add `training_config_hash` column: MD5/SHA of all model-affecting constants (`RIDGE_ALPHA`, `MAX_ADJUSTMENT`, `ALPHA_TO_SCORE_SCALE`, `DEGRADATION_WINDOW_COHORTS`, horizon period, CV parameters, etc.).
- Add `code_commit_sha` column: populated from `git rev-parse HEAD` at train time (best-effort, None if not in a git repo).
- Store `feature_schema_hash` (already exists), `training_horizon_version`, `training_cutoff` as separate columns — not encoded in the display name.
- `model_version` display name can stay human-readable for logs/dashboards.
- Migrate existing rows to set `model_id = model_version` for backward compat.

## Touches

- `agents/learning/calibration.py` — `ChallengerModel.train()`, `train_and_save()`
- `agent_db.py` — migration for `model_id`, `training_config_hash`, `code_commit_sha` on `learning_models`
- Any query that currently joins on `model_version` as primary identity
- `tests/test_calibration.py`

## Done when

- [ ] `learning_models` has `model_id UUID`, `training_config_hash TEXT`, `code_commit_sha TEXT`
- [ ] Two trains with identical features/cutoff but different `RIDGE_ALPHA` produce different `training_config_hash` values
- [ ] `model_id` is the primary join key for `model_observations`, `model_performance_snapshots`, and `model_promotion_log`
- [ ] `model_version` is preserved as human-readable display only
- [ ] Backward-compat migration sets `model_id = model_version` for existing rows
