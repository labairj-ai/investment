# Add Assignment-Policy Intake Question to Thesis Workflow

- **ID:** 0163
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** low
- **Depends:** none

## Problem

The `assignment_policy` block in `_CC_POLICY_DEFAULTS` defaults to fully permissive (`allowed=true`, `preserve_high_conviction=false`). This means a 5/5-conviction long-term compounder can be called away silently on assignment without the investor ever being asked their intent. For a portfolio system, assignment is effectively a stock-sale decision — the default should require an explicit choice, not be permissive by omission.

## Proposed approach

Add a single required question to the thesis intake flow (dashboard modal or `thesis_intake.py`):

> "If a covered call becomes deeply ITM, what should the system prioritize?"

With choices that translate directly to policy fields:

| UI choice | `assignment_policy` result |
|---|---|
| Preserve underlying (default for conviction ≥ 4) | `preserve_high_conviction: true, min_conviction_to_preserve: 4, min_thesis_health_for_preservation: 75` |
| Balanced | `preserve_high_conviction: false` (current default) |
| Prefer assignment | `preserve_high_conviction: false, only_if_overweight: false` |
| Only if overweight | `only_if_overweight: true` |

For new theses, treat a missing `assignment_policy` the same as "Preserve underlying" when conviction ≥ 4 rather than as "Balanced". For existing theses without the field, keep current permissive behaviour (backward compat).

The intake UI change is the main deliverable; backend policy logic is already in place.

## Touches

- `agents/thesis_intake.py` — add `assignment_policy` question and translation logic
- `generate_dashboard.py` — thesis intake modal: add the radio/select field
- `agents/covered_call_agent.py` — `_CC_POLICY_DEFAULTS`: optionally tighten default for high-conviction theses (open question: do this here or only in intake?)

## Done when

- [ ] Thesis intake presents assignment-policy preference question
- [ ] Choice is saved into `cc_policy.assignment_policy` on the thesis record
- [ ] Conviction ≥ 4 + no existing `assignment_policy` → intake defaults to "Preserve underlying"
- [ ] Existing theses without `assignment_policy` behave as before (no regression)
