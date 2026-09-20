# Population-Stratified Learning Metrics

- **ID:** 0427
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0419

## Problem

`base_recommendation_eligible` is now recorded per cohort in `learning_sweep_runs` (0419), but
`compute_prospective_metrics()` does not use it. All prospective ranking and decision-edge
metrics are computed over the undifferentiated cohort pool. This obscures a key analytical
question: does the challenger improve decisions within the existing strategy (base-eligible
sweeps) or does its apparent edge come mostly from days where the base strategy would not act?

## Proposed approach

- Join `learning_sweep_runs` on `decision_cohort_id` / `cohort_id` to get
  `base_recommendation_eligible` per cohort.
- In `compute_prospective_metrics()`, compute and return three sets of metrics:
  - `all_sweeps` — current behavior, unchanged
  - `eligible_sweeps` — cohorts where `base_recommendation_eligible = 1`
  - `ineligible_sweeps` — cohorts where `base_recommendation_eligible = 0`
- Return these as a nested dict (e.g., `{"all": {...}, "eligible": {...}, "ineligible": {...}}`).
- Surface both `all` and `eligible` populations in `learning_readiness_report()` and the
  Learning Readiness dashboard card.
- Do NOT change execution policy: PAPER_ACTIVE model still gates on the base-eligible pathway;
  shadow scoring on ineligible sweeps is analytical only.

## Touches

- `agents/learning/calibration.py` — `compute_prospective_metrics()` stratification
- `agents/learning/calibration.py` — `learning_readiness_report()` population labeling
- `serve.py` — `/api/learning/readiness` response shape (add stratified keys)
- `tests/test_calibration.py` — tests for stratified metric output

## Done when

- [ ] `compute_prospective_metrics()` returns stratified metrics for all/eligible/ineligible
- [ ] `learning_readiness_report()` exposes which population prospective evidence covers
- [ ] Readiness card shows separate ranking edge for base-eligible vs all sweeps
- [ ] PAPER_ACTIVE execution policy remains gated on base eligibility (no behavior change)
