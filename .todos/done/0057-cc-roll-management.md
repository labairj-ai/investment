# CC Roll / Management Recommendations

- **ID:** 0057
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

When a covered call position is approaching its management DTE (triggered by `cc_mgmt_dte`), the covered_call agent currently skips the ticker entirely (after fix in 0035 QA session). The user needs to know whether to ROLL the position (close + reopen at new strike/expiry) or let it expire. A SELL_CC recommendation over an existing open CC is wrong — the action should be ROLL_CC with full context on the existing position P&L.

## Proposed approach

- Add `_get_open_cc_position(ticker)` helper that returns the existing `cc_positions` row.
- When `_has_open_cc(ticker)` is True and the trigger is `cc_mgmt_dte`, run a roll analysis:
  - Fetch existing position (strike, expiry, contracts, open_premium, current mark-to-market)
  - Compute current P&L and DTE remaining
  - Find best roll target: same or higher strike, 30–60 DTE out
  - LLM receives existing position context + roll candidates → outputs ROLL or CLOSE recommendation
- Action type: `ROLL_CC` (new action type, not `SELL_CC`)
- Recommendation card in dashboard should show: existing position summary, roll target, net debit/credit, roll rationale

## Touches

- `agents/covered_call_agent.py` — add roll analysis path
- `agent_db.py` — add `ROLL_CC` to urgency severity map if needed
- `generate_dashboard.py` — ROLL_CC card rendering (show existing position + roll target)
- `config/strategy.json` urgency block — add `ROLL_CC` severity

## Done when

- [x] `cc_mgmt_dte` trigger for a ticker with open CC produces a `ROLL_CC` recommendation, not silence
- [x] Recommendation card shows: existing position (strike/expiry/P&L), proposed roll target, net credit/debit
- [x] `SELL_CC` recommendations never appear for tickers that already have an open CC position
- [x] **Backend QA:** deployed to optiplex, service running clean
- [x] **Frontend QA:** recommendations API healthy, ROLL_CC/CLOSE_CC in badge + urgency maps
- [x] **No service regression:** investment service active

## Outcome

Added `_get_open_cc_position()`, `_ROLL_SYSTEM`/`_ROLL_SCHEMA`, and `_analyze_roll()` to `covered_call_agent.py`. When `_has_open_cc()` is true, `_analyze_ticker()` now routes to `_analyze_roll()` instead of silently returning. Roll candidates are filtered to DTE≥30 and strike≥existing_strike. `action_payload` carries full existing-position context (strike/expiry/DTE/premium/current_mark/P&L) and roll-target context (strike/expiry/DTE/premium/net_credit). CLOSE_CC (LLM declines roll) writes a finding instead of a recommendation. Dashboard card shows existing position in red and roll target in green. ROLL_CC severity=0.8 in strategy.json (time-sensitive, higher than SELL_CC).
