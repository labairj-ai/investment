# Add Thesis/Portfolio Eligibility Gate to ALLOW_ASSIGNMENT

- **ID:** 0154
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** 0151

## Problem

`assignment_eligible()` checks delta, extrinsic, price floor, tax lots, and event risk -- but never asks: does the investor actually want to sell this stock?

A call being deep ITM doesn't mean assignment is desirable. For a 5/5 conviction holding with a 5+ year thesis and 94% thesis health, allowing assignment implicitly makes a stock-sale decision without considering portfolio intent. The covered-call module should not be able to override a deliberate long-term hold decision via option mechanics alone.

## Proposed approach

Add an `assignment_policy` block to the per-thesis `cc_policy` JSON (new optional fields, all default to permissive so existing behavior is unchanged when unset):

    {
      "assignment_policy": {
        "allowed": true,
        "only_if_overweight": false,
        "min_thesis_health_for_preservation": 80,
        "preserve_high_conviction": true,
        "min_conviction_to_preserve": 4
      }
    }

In `assignment_eligible()`, after the existing five checks, add:

1. If `allowed = false` -> reject ("assignment disabled by thesis policy")
2. If `preserve_high_conviction = true` AND thesis conviction >= `min_conviction_to_preserve`:
   - Fetch current thesis health score from DB
   - If thesis health >= `min_thesis_health_for_preservation` -> reject ("high-conviction healthy position -- prefer to hold")
3. If `only_if_overweight = true`:
   - Check current position weight vs thesis `max_position_pct`
   - If not overweight -> reject ("not overweight -- assignment would reduce below target")

`_CC_POLICY_DEFAULTS` should include `assignment_policy` with all fields set to permissive defaults (allowed=true, preserve_high_conviction=false).

The thesis intake UI (or manual edit) should expose these fields so the investor sets the intent once and it propagates automatically to CC decisions.

## Touches

- `agents/covered_call_agent.py` -- `assignment_eligible()` new thesis gate block; `_CC_POLICY_DEFAULTS`
- `agent_db.py` -- query for thesis health score (already exists via `get_active_thesis()`)
- Thesis intake modal / UI -- optional: expose assignment_policy fields
- `tests/test_covered_call_agent.py` -- tests for conviction-preservation and overweight gates

## Done when

- [x] `assignment_policy.allowed = false` in cc_policy blocks all assignment recommendations for that ticker
- [x] High-conviction healthy position with `preserve_high_conviction = true` is protected from assignment
- [x] `only_if_overweight = true` allows assignment only when position exceeds max_position_pct
- [x] All new fields default to permissive (no behavior change for existing theses without assignment_policy)
- [x] Existing tests pass
