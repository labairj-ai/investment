# Make model_observations Horizon-Version-Aware

- **ID:** 0373
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0372

## Problem

`model_observations` has a single `outcome_alpha_90d` column with no
`horizon_definition_version`. The outcome labeler back-fills this field only during
the `calendar_v1` 3m loop; the `sessions_v2` loop does not do the equivalent. This
means a model trained on `sessions_v2` labels gets its prospective evaluation
populated with `calendar_v1` outcomes (91 calendar days, not 63 trading sessions).
The 0365 prospective promotion gate and the 0371 degradation monitor both read
`outcome_alpha_90d` directly, so the version mismatch silently contaminates both the
OBSERVE→PAPER_ACTIVE gate and the ongoing degradation signal.

## Proposed approach

Add to `model_observations`:
- `target_horizon_version TEXT` — version the model was trained on (copied from
  `learning_models.training_horizon_version` at observation-write time)
- `outcome_horizon_version TEXT` — version of the outcome that was back-filled

When the labeler back-fills outcomes, only update an observation row whose
`target_horizon_version` matches the version of the outcome being written:

```sql
UPDATE model_observations
SET outcome_alpha_90d=?, outcome_horizon_version=?, outcome_labeled_at=?
WHERE episode_id=?
  AND outcome_alpha_90d IS NULL
  AND target_horizon_version=?   -- only match the model's target version
```

`compute_prospective_metrics()` and `_check_degradation()` should filter on
`target_horizon_version = model.training_horizon_version` so no cross-version
outcomes are included in evaluation.

When `score_for_observe()` writes a new prediction row, set `target_horizon_version`
from the model's `training_horizon_version`.

## Touches

- `agent_db.py` — `_new_cols`: `target_horizon_version TEXT`, `outcome_horizon_version TEXT`
  on `model_observations`
- `agents/learning/challenger.py` — `score_for_observe()`: populate `target_horizon_version`
- `agents/learning/outcome_labeler.py` — version-gated UPDATE in the calendar_v1 and
  sessions_v2 labeling loops
- `agents/learning/calibration.py` — `compute_prospective_metrics()`,
  `_check_degradation()`: filter by `target_horizon_version`
- `tests/test_calibration.py` — test that a sessions_v2-trained model's prospective
  evaluation only uses sessions_v2 outcomes

## Done when

- [ ] `model_observations.target_horizon_version` populated at prediction-write time
- [ ] `outcome_alpha_90d` back-fill is version-gated: calendar_v1 outcomes only update
  calendar_v1-targeted predictions; sessions_v2 outcomes only update sessions_v2-targeted ones
- [ ] `compute_prospective_metrics()` filters by `target_horizon_version`
- [ ] `_check_degradation()` filters by `target_horizon_version`
- [ ] Test: mixed-version scenario produces no cross-contamination
- [ ] `python -m pytest tests/` passes with no regressions
