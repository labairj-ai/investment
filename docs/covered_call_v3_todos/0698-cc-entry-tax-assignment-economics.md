# Add Covered Call Entry-Time Tax and Assignment Economics

- **ID:** 0698
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0690

## Problem

The management engine already contains substantial tax-friction and assignment logic, but initial SELL_CC selection can establish a call whose assignment would be inconsistent with lot age, assignment floor, or thesis policy.

Tax implications should be considered before opening the call, not only after the position becomes threatened.

## Proposed approach

For each candidate estimate and persist:

- shares/lots potentially delivered
- projected holding-period state at expiry
- projected assignment gain
- estimated ST-vs-LT friction when measurable
- assignment floor compatibility
- qualified-covered-call eligibility/warning state
- ex-dividend/early-assignment risk flag
- thesis assignment acceptability

Separate:

- `expected_tax_cost`: modeled economic cost used by V3 utility
- `tax_rule_warning`: deterministic warning/classification that should not be reduced to a dollar estimate

Reuse existing lot-schedule and assignment-friction utilities rather than duplicating tax logic.

## Guardrails

- This is decision support, not tax advice.
- Do not fabricate lot data when unavailable.
- Missing tax data must be explicit.
- Do not create a new contradictory tax engine.

## Done when

- [ ] Entry scoring can reject a call whose assignment violates explicit assignment policy.
- [ ] Lots nearing LT transition can affect expected tax cost.
- [ ] Qualified-covered-call warning/eligibility state is exposed.
- [ ] Ex-dividend early-assignment risk is captured.
- [ ] Tax calculations reuse existing lot/tax primitives.
- [ ] Assumptions and unavailable data are auditable.
