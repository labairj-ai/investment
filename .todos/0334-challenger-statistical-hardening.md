# Challenger Statistical Hardening: Cohorts, Real Walk-Forward, Remove Fake p_outperform

- **ID:** 0334
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0331, 0332, 0333

## Problem

The current challenger (0330) has three statistical correctness issues that would produce false confidence in any model that trains:

**1. Raw row count ≠ independent observations.**
The training query treats every episode row as an independent sample. If Opportunity Hunter evaluates MSFT, ANET, GRMN, etc. every day, many nearly-duplicated observations accumulate with overlapping 90-day return windows. Thirty rows could represent only a few decision dates and one market regime. Yet `reliability` and activation are gated directly on `training_n`. A ticker scored on September 15, 16, 17, and 18 is not four independent observations of that stock's alpha potential.

**2. The single 80/20 split is not walk-forward validation — and at n=30 it has zero validation rows.**
`split = max(30, int(n * 0.8))` means at exactly n=30, all 30 rows are training data and the validation set is empty. At n=31, validation has one row. Yet the model meets the activation threshold. Time-ordered data with correlated observations requires repeated folds with a gap/embargo so training and validation return windows do not heavily overlap.

**3. `p_outperform` is not a probability.**
`sigmoid(predicted_alpha × 100)` produces a number between 0 and 1, but there is no statistical basis for interpreting it as the probability of beating SPY. A predicted alpha of +3% becomes ~95% regardless of whether historical residuals support anything near 95%. This is not probability calibration.

## Proposed approach

**Effective sample size tracking:**
- Add four columns to `learning_models`: `unique_tickers`, `unique_decision_dates`, `unique_weeks`, `raw_n`.
- Write all four at `train_and_save()` time by querying the training set.
- `unique_decision_dates` = number of distinct decision-date calendar dates in the training corpus.
- `unique_weeks` = number of distinct ISO weeks.
- Any reporting of model readiness must display all four, not just raw row count.

**Replace single 80/20 split with decision-date cohort walk-forward:**
- Split by decision date, not by row index. Group episodes into date-ordered cohorts (e.g., weekly or monthly buckets).
- Use repeated walk-forward folds: train on cohorts 1..k, validate on cohort k+1 (with a gap/embargo of ≥ one return-horizon to avoid return-window overlap). Repeat for k = min_folds..last-1.
- Report mean and std of validation MAE across folds, not a single holdout metric.
- Also report baseline MAE = predicting the historical mean alpha (no model) — challenger must beat this baseline to be considered trained, not just meet a row threshold.
- Directional stability: check that Ridge coefficient signs are reasonably consistent across folds; flag instability.

**Ranking value check:**
- Add a quintile rank validation: does the top predicted-alpha quintile outperform the bottom quintile in the validation set? Report this as `top_vs_bottom_quintile_alpha`.

**Remove `p_outperform`:**
- Delete `p_outperform` from `ChallengerModel.score()` output and all downstream consumers (Learning Lab, opportunity agent log, etc.).
- Report only `expected_alpha`, `reliability`, `learning_adjustment`, `model_version`.
- Document: a future item will train an explicit binary outcome model (alpha > 0 vs ≤ 0) and evaluate calibration via Brier score + reliability curves. That is not this item.

**Validation baselines to record:**
- Null model MAE (predict mean alpha)
- Challenger cross-validated MAE (mean across folds)
- Challenger vs null improvement (must be positive to consider model useful)
- Top-vs-bottom quintile alpha spread

All recorded in `validation_metrics_json` on `learning_models`.

## Touches

- `agents/learning/calibration.py` — replace single split with repeated cohort walk-forward; add baseline computation; add quintile ranking; add unique_tickers/dates/weeks tracking; remove p_outperform
- `agents/learning/challenger.py` — remove p_outperform from score result
- `agents/opportunity_agent.py` — remove any reference to p_outperform
- `generate_dashboard.py` / `serve.py` — remove p_outperform from Learning Lab display
- `db/migrations/` — add `unique_tickers`, `unique_decision_dates`, `unique_weeks`, `raw_n` to `learning_models`
- `tests/` — assert walk-forward produces multiple folds; assert baseline MAE is computed; assert p_outperform absent; assert unique_* columns populated

## Done when

- [ ] `unique_tickers`, `unique_decision_dates`, `unique_weeks`, `raw_n` recorded in `learning_models` at training time
- [ ] Training uses decision-date cohort walk-forward folds with embargo; no single 80/20 row-index split
- [ ] Baseline (null model MAE) computed and compared; challenger must beat baseline before being considered trained
- [ ] `top_vs_bottom_quintile_alpha` computed and stored in `validation_metrics_json`
- [ ] Directional stability (coefficient sign consistency across folds) computed and stored
- [ ] `p_outperform` removed from all code paths — model, scorer, UI, tests
- [ ] `python -m pytest tests/` passes with no regressions
