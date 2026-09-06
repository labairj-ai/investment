# Build CC Management Decision Engine (Roll/BTC/Assignment)

- **ID:** 0051
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0039

## Problem

The Trigger Engine fires `cc_mgmt_dte` events when an open CC position approaches expiration, and the CC agent is registered to handle them — but the CC agent is fundamentally a new-contract selector. There is no actual decision framework for managing existing calls. The six outcomes (HOLD_CALL, ROLL_OUT, ROLL_UP, ROLL_UP_AND_OUT, BUY_TO_CLOSE, ALLOW_ASSIGNMENT) each have distinct conditions, P&L implications, and execution steps. Currently, a DTE trigger fires but the agent has no logic to distinguish between them.

## Proposed approach

- Create a deterministic sub-engine in `covered_call_agent.py` (or a new `agents/cc_management.py`) that handles `cc_mgmt_dte` trigger events.
- Decision tree (deterministic, no LLM):
  - Stock deeply ITM near expiry + no earnings → evaluate ALLOW_ASSIGNMENT vs ROLL_OUT
  - Stock OTM, premium decayed >80% → BUY_TO_CLOSE to capture remaining extrinsic
  - DTE ≤ 7 and still OTM → HOLD_CALL (let expire)
  - Stock moved up significantly but still OTM → ROLL_UP or ROLL_UP_AND_OUT
  - Earnings within 2 weeks → ROLL_OUT past earnings to avoid event risk
- LLM writes the rationale and confirms the action; it does not choose it.
- Produce a `Recommendation` with action from `{HOLD_CALL, ROLL_OUT, ROLL_UP, ROLL_UP_AND_OUT, BUY_TO_CLOSE, ALLOW_ASSIGNMENT}`.
- This engine runs when `ctx.trigger_type == "cc_mgmt_dte"`; the existing new-contract logic runs when `ctx.trigger_type == "cc_eligible"` (requires 0039 to be correct).

## Touches

- `agents/covered_call_agent.py` (or new `agents/cc_management.py`)
- `agents/contracts.py` (add new action values if needed)
- `agent_db.py` (ensure new action values accepted)

## Done when

- [x] `cc_mgmt_dte` trigger events produce a recommendation with one of the 6 management actions
- [x] HOLD_CALL recommendation produced for an OTM call with DTE ≤ 7
- [x] ALLOW_ASSIGNMENT recommendation produced for a deeply ITM call near expiry
- [x] BUY_TO_CLOSE recommended when extrinsic value has decayed to <20% of premium
- [x] Management path does not run when trigger is `cc_eligible` (new call path)
- [x] LLM rationale reflects the deterministic decision, not an independent assessment
- [x] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [x] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [x] **No service regression:** investment service still running; all existing API routes respond correctly after the change

## Outcome

Two files changed:

- **`agents/covered_call_agent.py`**: Replaced `_ROLL_SYSTEM`/`_ROLL_SCHEMA` with `_MGMT_SYSTEM`/`_MGMT_SCHEMA`. Added `_decide_mgmt_action()` — deterministic 6-way decision in priority order: earnings risk → ROLL_OUT, deeply ITM + DTE≤14 → ALLOW_ASSIGNMENT, pct_captured≥80 → BUY_TO_CLOSE, DTE≤7 + OTM → HOLD_CALL, near/at/above strike → ROLL_UP_AND_OUT, delta≥0.30 → ROLL_UP, else → HOLD_CALL. Rewrote `_analyze_roll` to call `covered_call_rec.evaluate_open_position()` (live mark + delta + risk events), apply the decision tree, then ask LLM for rationale only. All 6 decision paths verified via unit test.
- **`config/strategy.json`**: Added severity entries for ROLL_OUT (0.75), ROLL_UP_AND_OUT (0.75), ROLL_UP (0.7), BUY_TO_CLOSE (0.7), ALLOW_ASSIGNMENT (0.6), HOLD_CALL (0.1) so urgency scoring works for new action types.
