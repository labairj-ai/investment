# Training Algorithm Identity

- **ID:** 0428
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0420

## Problem

0420 added the hyperparameter config hash to `model_version`, preventing silent collisions when
`ridge_alpha` or other tuning constants change. But the config hash inputs are hyperparameters
and feature schema — not the training algorithm itself. A refactor of `_cv_walk_forward()`,
a change to how walk-forward folds are selected, or a bug fix in the Ridge fit path can
produce a functionally different model with an identical `model_version`. `code_commit_sha` is
recorded separately as provenance metadata but does not influence the model key, so an INSERT
with the same cutoff and hyperparams would still collide.

Hashing the full Git SHA into model identity is too broad: unrelated code changes (dashboard
edits, canary scripts) would create spurious new model versions.

## Proposed approach

- Define an explicit `TRAINING_ALGORITHM_VERSION` constant in `calibration.py` (e.g. `"ridge_v1"`).
- Include this string in `_training_config_hash()` inputs so it contributes to the config hash.
- Increment this constant (to `ridge_v2`, etc.) only when the training algorithm materially
  changes: fold-selection logic, embargo calculation, feature normalization, the Ridge fit itself.
- This means algorithm changes produce a new `model_version` without requiring a full
  schema migration, and cosmetic/unrelated code changes do not affect model identity.
- Document the convention in a comment next to the constant.

## Touches

- `agents/learning/calibration.py` — `TRAINING_ALGORITHM_VERSION` constant + include in config hash
- `tests/test_calibration.py` — test that different algorithm version produces different model_version

## Done when

- [ ] `TRAINING_ALGORITHM_VERSION` constant exists and is included in `_training_config_hash()`
- [ ] A material algorithm change (simulated by changing the constant) produces a new `model_version`
- [ ] Constant is documented with guidance on when to increment it
