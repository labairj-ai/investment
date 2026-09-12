# Unify Duplicate CC Management Decision Engines

- **ID:** 0152
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** high
- **Depends:** 0151

## Problem

There are currently two independent CC management decision hierarchies that can produce different advice about the same option.

`covered_call_rec.py` `_eval_open_economics()` uses: risk event -> buy_back; high delta near expiry -> roll; stock above strike -> roll; high delta -> roll.

`covered_call_agent.py` `_decide_mgmt_action()` uses: cap pct >= 80% -> BTC; assignment_eligible() -> ALLOW_ASSIGNMENT; risk event -> ROLL_OUT; high premium captured -> BTC; ITM/near-money -> ROLL_UP_AND_OUT.

For a deeply ITM position with event risk, the first engine may say "roll" while the second says "ALLOW_ASSIGNMENT". Different dashboard views and API consumers can give inconsistent recommendations about the same live option. Inconsistent recommendations destroy confidence faster than missing features.

## Proposed approach

Create a single canonical function evaluate_cc_management_state(ticker, position, policy, ctx) in covered_call_agent.py (or a new shared module) returning one action + reason string. Proposed hierarchy:

1. Cap pct >= 80% -> BUY_TO_CLOSE
2. assignment_eligible() -> ALLOW_ASSIGNMENT (0139 logic, fixed per 0151)
3. Upcoming avoid-event within 14d -> ROLL_OUT
4. Deep ITM (delta >= 0.70) + DTE <= 21 -> ROLL_UP_AND_OUT
5. Near expiry (DTE <= 14) any ITM -> ROLL_UP
6. Otherwise -> HOLD_CALL

`covered_call_agent.py` removes `_decide_mgmt_action()` and calls `evaluate_cc_management_state()`; `covered_call_rec.py` strips management-advice logic from `_eval_open_economics()` (keep analytics only -- cc_alpha, regret_prob, vol model); the LLM explains the decision, it does not run a second decision ladder.

## Touches

- `agents/covered_call_agent.py` -- new `evaluate_cc_management_state()`, remove `_decide_mgmt_action()`
- `covered_call_rec.py` -- strip management-action hierarchy from `_eval_open_economics()`; keep option analytics
- `tests/test_covered_call_agent.py` -- determinism tests against single function
- Dashboard/API endpoints that duplicate management logic

## Done when

- [x] Single `evaluate_cc_management_state()` is the only CC management decision point
- [x] `covered_call_rec.py` no longer contains a management action hierarchy
- [x] Dashboard and agent both call the same function path
- [x] Deeply-ITM + event risk produces the same action regardless of call path
- [x] Existing tests pass; new determinism tests added
