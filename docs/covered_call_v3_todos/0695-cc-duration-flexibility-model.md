# Add Covered Call Duration and Flexibility Economics

- **ID:** 0695
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0693, 0694

## Problem

A longer-dated covered call commits the upside cap for more time and reduces the opportunity to reprice volatility, strike, and thesis state. Comparing contracts using absolute premium or annualized return alone does not value this flexibility.

## Proposed approach

Add duration-normalized metrics:

- `premium_per_day`
- `cc_alpha_per_day`
- `adjusted_cc_alpha_per_day`
- `theta_efficiency`
- `management_risk_per_day`

Add a conservative sequential-short-cycle benchmark.

Example: compare a 56-DTE candidate with a modeled 28-DTE call plus a conservative estimate of the opportunity to write again after the first expiry.

Do not assume current IV, drift, or skew persist unchanged into the second cycle.

Add configurable preferred DTE bands by CC strategy, initially policy defaults rather than learned truth.

## Guardrails

- Sequential benchmark must use conservative assumptions.
- Do not assume continuous option-writing availability.
- Preferred DTE bands are policy, not evidence of superiority.
- No hard-coded 30-DTE universal rule.

## Done when

- [ ] Long-duration candidates are compared with a shorter-cycle flexibility benchmark.
- [ ] Duration-normalized economics are available to V3 utility.
- [ ] Flat, inverted, and upward IV term structures produce intuitive results in tests.
- [ ] DTE preferences are configurable per thesis/policy.
- [ ] No raw-premium duration bias remains in V3.
