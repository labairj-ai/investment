# Fix Beta Concordance Logic and Add Confidence Gating

- **ID:** 0483
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0473

## Problem

The beta-vs-LLM agreement check in `_compute_equity_betas` is directionally reversed: a strongly negative `rate_beta_100bp_return_pct` (stock falls significantly when yields rise) should support HIGH `rate_sensitivity`, but the current logic treats it as supporting LOW sensitivity. Additionally, the regression conflates broad equity market moves with rate/USD sensitivity because there is no market-return (SPY) control, and weak betas (low t-stat, low R²) are presented to the LLM with the same weight as statistically strong estimates.

## Proposed approach

- **Fix concordance direction**: invert the comparison — `rate_beta < -5` supports HIGH rate_sensitivity (≥6); `rate_beta > -2` supports LOW (≤4). Same directional fix for USD beta.
- **Add SPY control**: download weekly SPY returns over the same lookback window and add as a third regressor (`y ~ const + yield_change + uup_return + spy_return`). The partial coefficients on yield/UUP then reflect idiosyncratic sensitivity after controlling for market beta.
- **Confidence metadata**: compute confidence tier from rate_beta_tstat — `< 1.5` → `"weak"`, `1.5–2.0` → `"suggestive"`, `≥ 2.0` → `"stronger"`. Store as `rate_beta_confidence` and `usd_beta_confidence` in the betas dict.
- **Gate LLM input**: only include beta values in the scoring evidence block when confidence is `"suggestive"` or `"stronger"`; weak betas get a note like `"rate factor: insufficient data (t<1.5)"` instead.

## Touches

- `portfolio_ai.py` — `_compute_equity_betas()`, beta-vs-LLM agreement logic, evidence block assembly
- `tests/test_macro_betas.py` — add concordance direction tests

## Done when

- [ ] A stock with `rate_beta_100bp_return_pct = -12` produces agreement (not warning) for `rate_sensitivity = 8`
- [ ] SPY return is a regressor; rate/USD betas are partial coefficients after market control
- [ ] `rate_beta_confidence` and `usd_beta_confidence` fields present in betas dict
- [ ] Weak betas (t-stat < 1.5) are not shown to the LLM as quantitative evidence
