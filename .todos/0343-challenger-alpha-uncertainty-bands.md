# Challenger Expected-Alpha Uncertainty Bands

- **ID:** 0343
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** low
- **Depends:** 0334

## Problem

The current challenger model surfaces `expected_alpha = +2.8%` as a point estimate. That precision is false: the estimate has meaningful uncertainty from limited training data, noise in alpha measurement, and distribution shift between training and live conditions. Displaying a bare point estimate in the Learning Lab implies more confidence than is warranted and makes it hard to judge whether a model is genuinely informative or just fitted to noise.

A reader needs to see something like:
```
Expected alpha: +2.8%
Historical uncertainty: ±4.6%
Reliability: LOW
```

## Proposed approach

Bootstrap confidence intervals by decision-date cohort:
- Resample fold-level alpha predictions (not raw episodes) with replacement, N=1000 iterations
- Report 10th and 90th percentile of bootstrapped mean alpha as the uncertainty band
- Classify reliability: HIGH if band width < 2%, MEDIUM if < 5%, LOW otherwise (thresholds config-driven)
- Store `alpha_ci_low`, `alpha_ci_high`, `alpha_reliability` in `learning_models.validation_metrics` JSON (no schema change needed if using existing JSON blob)
- Surface in Learning Lab: show the CI band below the point estimate card

**Do not use uncertainty to modify scoring yet.** This is an interpretation layer only — the model still applies its full adjustment when PAPER_ACTIVE. Uncertainty is surfaced for human judgment during promotion decisions.

## Touches

- `agents/learning/calibration.py` — `_cv_walk_forward()`: after fold collection, bootstrap resample fold alpha means; add `alpha_ci_low`, `alpha_ci_high`, `alpha_reliability` to validation metrics dict
- `serve.py` / `generate_dashboard.py` — Learning Lab model card: display CI band and reliability label alongside expected alpha
- `tests/test_calibration.py` — assert `alpha_ci_low` and `alpha_ci_high` present in validation metrics and `ci_low <= alpha_mean <= ci_high`

## Done when

- [x] `validation_metrics` JSON includes `alpha_ci_low`, `alpha_ci_high`, `alpha_reliability` after training with sufficient CV folds
- [x] `alpha_ci_low <= expected_alpha <= alpha_ci_high` always holds
- [x] Reliability classification (`HIGH`/`MEDIUM`/`LOW`) present and config-driven
- [x] Learning Lab model card displays uncertainty band and reliability label
- [x] Models with 0 CV folds: CI fields are `null`, reliability is `"INSUFFICIENT_DATA"`
- [x] `python -m pytest tests/` passes with no regressions

## Outcome

3 files changed. `agents/learning/calibration.py`: added `ALPHA_CI_HIGH_THRESHOLD = 0.02` and `ALPHA_CI_MEDIUM_THRESHOLD = 0.05` constants; new `_bootstrap_alpha_ci(folds, n_iter=1000)` function bootstraps fold top-vs-bottom-quintile-alpha spreads with replacement, reports 10th/90th percentile CI and classifies reliability HIGH/MEDIUM/LOW/INSUFFICIENT_DATA; `ChallengerModel.train()` calls `_bootstrap_alpha_ci()` and stores results in `validation_metrics` as `alpha_ci_low`, `alpha_ci_high`, `alpha_reliability`. `serve.py` `_handle_learning_stats()`: added `active_model_card` key in response with CI fields. `generate_dashboard.py`: added "Active Challenger Model" card to Learning Lab HTML; `loadLearningPanel()` renders point estimate, CI band, reliability badge, beats_baseline flag. 7 new tests in `TestAlphaUncertaintyBands0343`. 820 passed.
