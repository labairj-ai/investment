# Add Dynamic Covered Call Overwrite Fraction

- **ID:** 0696
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0694

## Problem

Initial SELL_CC sizing currently approximates:

`contracts = shares // 100`

This overwrites every available round lot. It treats coverage percentage as an implementation detail even though it is a core strategy decision, especially for high-conviction compounders where assignment of the full covered amount can create excessive opportunity cost.

## Proposed approach

Make the decision tuple:

`(write_or_not, overwrite_fraction, strike, expiry)`

Support policy-constrained fractions such as:

- 0%
- 25%
- 50%
- 75%
- 100%

subject to 100-share contract granularity.

Inputs may include:

- thesis CC strategy
- conviction
- thesis health
- current portfolio weight vs max
- valuation/assignment floor
- momentum/regime state when available
- V3 utility
- management risk
- tax friction

Initial defaults should be explicit policy, not learned weights.

Store:

- `eligible_contracts_max`
- `recommended_contracts`
- `overwrite_fraction`
- `overwrite_policy_version`

## Guardrails

- Never recommend more contracts than covered shares support.
- Partial overwrite must not silently change tax-lot assumptions.
- High conviction should not be a guaranteed veto; it should constrain coverage/upside cost.
- Any adaptive coverage policy must wait for prospective evidence.

## Done when

- [ ] The agent can recommend 1 call against 300 shares.
- [ ] Contract count is no longer always `shares // 100`.
- [ ] Strategy-specific maximum overwrite fractions are configurable.
- [ ] Recommendation payload and UI show recommended coverage percentage.
- [ ] Outcome attribution records original overwrite fraction.
- [ ] Assignment cannot exceed policy-authorized share coverage.
