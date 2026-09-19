# Correct Rate-Beta Units and Use Multivariate OLS

- **ID:** 0473
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** none

## Problem

The rate-beta calculation in `_compute_equity_betas()` has a unit error: the independent variable is constructed as `tnx.diff() * 100` (units: basis points), so the raw OLS coefficient is equity decimal return per 1 bp change — not per 100 bps as documented. The result is off by a factor of 100, making every downstream comparison and threshold check (e.g. `rate_beta < -0.02`) operate against the wrong scale. Additionally, rate and USD betas are estimated with two separate univariate regressions, leaving omitted-variable bias in both when yield changes and dollar moves are correlated (which they frequently are).

## Proposed approach

- Fix the rate-beta computation: either keep the independent variable in bps and multiply the coefficient by 100, or convert the independent variable to percent (divide by 100) so the coefficient naturally reads as "equity return per 100bp yield change." Store as `rate_beta_100bp_return_pct` (a −10 means the stock falls ~10% for a +100bp yield move).
- Fix USD beta similarly: store as `usd_beta_1pct_return_pct` (equity % return per +1% UUP return).
- Replace two separate `_ols(y, x)` calls with a single multivariate OLS: `y ~ const + yield_change_bps + uup_return`. Use numpy's `lstsq` or a simple matrix solve; no external stats library needed.
- Store full diagnostic metadata alongside the betas: `r_squared`, `rate_beta_se`, `usd_beta_se`, `rate_beta_tstat`, `usd_beta_tstat`, `n_weeks`, `lookback_start`, `lookback_end`.
- Update all downstream thresholds and log messages to use the corrected units.
- Add unit tests in `tests/test_macro_betas.py` using synthetic data with a known exact relationship (e.g. equity return = −0.10 × yield_change_100bp) and assert the recovered coefficient is within tolerance.

## Touches

- `portfolio_ai.py` — `_compute_equity_betas()` and downstream threshold comparisons
- `tests/` — new `tests/test_macro_betas.py`

## Done when

- [x] A synthetic test with known rate beta = −10%/100bp recovers that value within ±0.5%
- [x] Stored field is named `rate_beta_100bp_return_pct` and the docstring matches the unit
- [x] Multivariate OLS replaces the two univariate regressions
- [x] `r_squared`, SE, t-stat, `n_weeks`, `lookback_start`, `lookback_end` stored per beta computation
- [x] All downstream agreement thresholds updated to the corrected unit scale
