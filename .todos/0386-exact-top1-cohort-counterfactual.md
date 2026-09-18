# Fix base_would_select to Select Exactly Top-1 Candidate

- **ID:** 0386
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** none

## Problem

`base_would_select` in `score_for_observe()` currently marks the top quintile of candidates by base_score (e.g. 5 candidates out of 25), while `would_select` marks exactly 1 (max challenger_score). `compute_prospective_metrics()` then compares the single challenger winner against the average of those 5 base candidates — that is not the champion/challenger experiment the system is supposed to run. A worse challenger can appear beneficial if the base quintile average is dragged down by bad picks 2–5. The correct comparison is: max(base_score) vs max(challenger_score), same cohort.

## Proposed approach

- In `score_for_observe()`: change `base_would_select` to mark exactly 1 row — the one with `max(base_score)` per cohort run, mirroring `would_select`.
- Store `base_selected_episode_id` and `challenger_selected_episode_id` on `model_observations` (or derive them from existing columns) so divergence can be determined by identity, not outcome-list equality.
- In `compute_prospective_metrics()`: when computing `selection_alpha_delta` via cohort map, compare the single base-selected outcome to the single challenger-selected outcome per cohort. Divergence = `base_episode_id != challenger_episode_id`, not list comparison.
- Add `_new_cols` migration entries for any new columns.
- Update tests: assert exactly one `base_would_select=1` row per cohort; assert `selection_alpha_delta` reflects only truly divergent cohorts.

## Touches

- `agents/learning/challenger.py` — `score_for_observe()`
- `agents/learning/calibration.py` — `compute_prospective_metrics()`, cohort delta logic
- `agent_db.py` — `_new_cols` migration if new columns added
- `tests/test_calibration.py` — `TestDecisionCohortEvaluation0382`

## Done when

- [ ] `base_would_select=1` for exactly one row per `decision_cohort_id` (max base_score)
- [ ] `selection_alpha_delta` in `compute_prospective_metrics()` compares single base vs single challenger candidate per cohort
- [ ] Divergence determined by episode/ticker identity, not outcome-list equality
- [ ] Existing tests updated; new test asserts exactly-1 base selection per cohort
- [ ] Full test suite passes
