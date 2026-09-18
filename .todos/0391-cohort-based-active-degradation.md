# Add Same-Cohort Selection Edge to Degradation Monitor

- **ID:** 0391
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0386, 0387, 0388

## Problem

`_check_degradation()` monitors PAPER_ACTIVE models using ranking spread (does the full ordering look better?) but not selection delta (did the actual investment the learner changed produce better outcomes than what the base strategy would have chosen?). Ranking spread catches broad deterioration but can miss the case where the model re-ranks candidates correctly on average while consistently making worse top-1 choices — the decision that actually matters.

## Proposed approach

- After 0386/0387/0388 establish exact top-1 cohort comparisons and stable cohort IDs:
  - Add `snapshot_selection_delta` and `n_divergent_cohorts_in_window` to `model_performance_snapshots` schema.
  - In `_check_degradation()`: for observations in the rolling window, compute the cohort-matched selection delta (challenger top-1 outcome minus base top-1 outcome, over divergent cohorts only).
  - Add to NEGATIVE verdict logic: sustained negative `selection_delta` across sufficient divergent cohorts → NEGATIVE signal.
  - Require `n_divergent_cohorts_in_window >= minimum_divergent_cohorts` (new constant, e.g. 5) before using this metric to emit a NEGATIVE verdict.
- Both `ranking_spread < 0` AND `selection_delta < 0` (with sufficient sample) can independently trigger NEGATIVE. Combined sustained negatives in both dimensions should be treated as strong signal.
- Update `model_performance_snapshots` schema migration.

## Touches

- `agents/learning/calibration.py` — `_check_degradation()`
- `agent_db.py` — `_new_cols` for `snapshot_selection_delta`, `n_divergent_cohorts_in_window`
- `tests/test_calibration.py` — new `TestCohortBasedDegradation0391`

## Done when

- [ ] `model_performance_snapshots` stores `snapshot_selection_delta` and `n_divergent_cohorts_in_window`
- [ ] Sustained negative `selection_delta` with enough divergent cohorts triggers NEGATIVE verdict
- [ ] Guard: metric not used until `n_divergent_cohorts_in_window >= minimum` (to avoid noise with few comparisons)
- [ ] Existing degradation tests still pass; new tests cover the new signal
- [ ] Full test suite passes
