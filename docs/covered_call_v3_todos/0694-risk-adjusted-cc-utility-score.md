# Replace Covered Call Composite Score With Risk-Adjusted Utility

- **ID:** 0694
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0691, 0692, 0693

## Problem

Percentile-based scoring guarantees that every candidate universe has a relative winner even when all available trades are economically unattractive.

The production question should be whether writing the call adds sufficient risk-adjusted value versus doing nothing.

## Proposed approach

Introduce a V3 absolute utility model.

Start from decomposed economics:

```
adjusted_cc_alpha =
    expected_premium
  - expected_upside_surrendered
  - expected_management_cost
  - expected_execution_cost
  - expected_tax_cost
```

Also compute:

- `adjusted_cc_alpha_pct`
- `adjusted_cc_alpha_per_day`
- `expected_upside_surrendered`
- `expected_management_cost`
- `expected_execution_cost`
- `expected_tax_cost`
- `utility_hurdle`
- `utility_margin`

Use absolute thresholds, not only within-universe ranks.

NO_CALL must be a normal outcome whenever the best candidate fails the absolute hurdle.

Keep the existing V2 score for champion/challenger comparison until 0702.

## Guardrails

- No opaque LLM-created weights.
- Every utility value must reconcile to persisted components.
- No double-counting roll risk and upside surrender.
- Economic values should use consistent per-share or per-contract units and explicitly document them.
- Missing required inputs should fail closed or lower confidence.

## Done when

- [ ] Every V3 candidate utility reconciles exactly to its components.
- [ ] A universally bad synthetic universe returns NO_CALL.
- [ ] Longer DTE does not win merely because nominal premium is larger.
- [ ] V3 utility has a semantic/versioned contract.
- [ ] Deterministic tests cover favorable, neutral, and unfavorable call-writing environments.
- [ ] Existing V2 score remains available for comparison.
- [ ] V3 remains non-production until 0702 promotion criteria are met.
