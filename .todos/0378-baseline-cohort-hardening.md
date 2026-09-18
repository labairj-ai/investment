# Harden Prospective Baseline and Cohort Independence

- **ID:** 0378
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0375

## Problem

Two statistical weaknesses in `compute_prospective_metrics()`:

**1. Look-ahead baseline.** `baseline_mae` is computed as `mean(|mean_alpha - outcome|)`,
where `mean_alpha` is the hindsight mean of all observed `outcome_alpha_90d` values.
This is not a valid baseline: a real naive predictor has no access to future outcomes.
It should use the model's training-time `mean_alpha` (stored in `train_metrics_json`),
or better, a `baseline_predicted_alpha` persisted at prediction time in
`model_observations`.

**2. Cohort-day clustering.** On any single Opportunity Hunter cycle, all candidates
scored that day share the same market conditions. If 20 candidates are scored on one
volatile day, their outcomes are correlated — treating them as 20 independent
observations inflates the apparent sample size. The 0365 implementation counts
`prospective_selected_n` and uses a 20-observation threshold, but 20 rows from 2 days
is not the same as 20 rows from 20 days. Ranking spread and MAE estimates computed
over a few high-count days can be misleading.

## Proposed approach

**Baseline fix:**
- At observation-write time in `score_for_observe()`, store
  `baseline_predicted_alpha` from the model's `train_metrics_json["mean_alpha"]`
  (or a running mean of training outcomes) directly in the `model_observations` row
- `compute_prospective_metrics()` computes `baseline_mae` as
  `mean(|baseline_predicted_alpha - outcome|)` per row, using the at-prediction-time
  baseline — no hindsight

**Cohort independence:**
- Add `scored_at_date TEXT` to `model_observations` (date portion of
  `scored_at` timestamp, already present)
- `compute_prospective_metrics()` reports:
  - `n_cohort_days` — COUNT DISTINCT scored_at_date for rows with outcomes
  - `effective_n` — min(prospective_n, 3 * n_cohort_days) as a conservative
    independent-observation estimate
- Add a gate: `n_cohort_days >= 10` before trusting ranking spread estimates
  (10 independent market days required, not just 20 rows)

## Touches

- `agent_db.py` — `_new_cols`: `baseline_predicted_alpha REAL` on `model_observations`
- `agents/learning/challenger.py` — `score_for_observe()`: populate
  `baseline_predicted_alpha` from model's training mean alpha
- `agents/learning/calibration.py` — `compute_prospective_metrics()`: use
  per-row `baseline_predicted_alpha` for `baseline_mae`; compute `n_cohort_days` and
  `effective_n`; add `n_cohort_days >= 10` gate
- `tests/test_calibration.py` — test that baseline_mae uses at-prediction baseline not
  hindsight mean; test that 20 rows from 1 day fails the cohort_days gate

## Done when

- [ ] `model_observations.baseline_predicted_alpha` populated at write time from
  training-time mean
- [ ] `baseline_mae` in `compute_prospective_metrics()` uses per-row
  `baseline_predicted_alpha`, not hindsight outcome mean
- [ ] `n_cohort_days` and `effective_n` reported in prospective metrics
- [ ] `n_cohort_days >= 10` gate added to OBSERVE→PAPER_ACTIVE check
- [ ] Test: baseline_mae unchanged if outcomes shift (proving no look-ahead)
- [ ] Test: model with 20 rows from 1 day fails cohort gate; from 10 days passes
- [ ] `python -m pytest tests/` passes with no regressions
