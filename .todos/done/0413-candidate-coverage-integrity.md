# Audit Candidate Coverage Per Learning Cohort

- **ID:** 0413
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0411, 0412

## Problem

The current winner-count integrity check only validates cohorts already present in `model_observations`. A completely missing cohort (zero rows written) or a partial candidate universe (some candidates silently skipped due to the `_q`/`q_score` mismatch) looks clean because there is nothing to group and flag. Every candidate episode carries the OH `run_id`, so it is possible to cross-reference the expected candidate count against what was actually scored.

## Proposed approach

- For each (model_version, decision_cohort_id) group in `model_observations`, resolve the OH `run_id` from the associated `decision_episodes`.
- Count scoreable `decision_episodes` for that run (episodes with all five component scores non-null and a matching `feature_schema_version`).
- Assert that `COUNT(model_observations) == COUNT(scoreable_episodes)` for the cohort.
- Flag partial cohorts as BLOCK and zero-row cohorts (where a cohort_id was generated but no observations written) as BLOCK.
- Add this check to `check_integrity.py` as `candidate_coverage`.
- Requires 0412 to land first so cohort_id is on decision_variants and the OH run can be resolved.

## Touches

- `check_integrity.py` — new `_check_candidate_coverage()` function
- `tests/test_calibration.py` or `tests/test_integrity.py` — inject partial coverage, assert BLOCK

## Done when

- [ ] `_check_candidate_coverage()` detects a cohort that has fewer `model_observations` rows than scoreable `decision_episodes` for its OH run
- [ ] Zero-observation cohorts are flagged as BLOCK
- [ ] Partial-coverage cohorts are flagged as BLOCK
- [ ] A clean cohort (all candidates scored) returns ok
- [ ] Tests for both the clean and violation cases
