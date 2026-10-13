# Add Path-Dependent Covered Call Management Risk

- **ID:** 0692
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0691

## Problem

Current regret is terminal:

`P(S_T > K + premium)`

This does not measure the failure mode that drives real user intervention: the stock touching or exceeding the strike, option delta rising, or the short call becoming expensive enough to trigger a roll before expiration.

A path can create substantial management burden even when terminal regret is zero.

## Proposed approach

Add path-dependent metrics for every candidate:

- `strike_touch_prob`: probability stock touches strike before expiry
- `regret_barrier_touch_prob`: probability stock touches strike + premium before expiry
- `delta30_touch_prob`: probability option reaches delta >= 0.30
- `delta50_touch_prob`: probability option reaches delta >= 0.50
- `expected_days_to_first_touch`
- `management_risk_model_version`

Use analytical GBM first-passage formulas where valid.

Add a deterministic Monte Carlo implementation as a validation oracle and future extension point. Monte Carlo must use fixed seeds in tests.

Derive a bounded `management_risk` summary only after individual components exist; do not hide the underlying metrics.

## Guardrails

- Keep terminal regret and expiry ITM probabilities; path metrics supplement them.
- Do not infer that touching automatically means a roll occurred.
- Do not use LLM judgment to estimate probabilities.
- Any Monte Carlo production use must persist seed policy/model version and be reproducible.

## Done when

- [ ] A contract can show low terminal regret and high touch/management risk.
- [ ] Tests include a synthetic path analogous to 100 -> 116 -> 107 and show terminal regret can be zero while path risk is non-zero.
- [ ] Analytical and Monte Carlo estimates agree within documented tolerance for simple GBM cases.
- [ ] Delta-threshold probabilities are tested against deterministic scenarios.
- [ ] All component metrics are exposed to the candidate payload.
- [ ] No combined management-risk score can exceed [0,1].
