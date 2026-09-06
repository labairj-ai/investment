# CC Roll / Management Recommendations

- **ID:** 0057
- **Status:** backlog
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

- [ ] `cc_mgmt_dte` trigger for a ticker with open CC produces a `ROLL_CC` recommendation, not silence
- [ ] Recommendation card shows: existing position (strike/expiry/P&L), proposed roll target, net credit/debit
- [ ] `SELL_CC` recommendations never appear for tickers that already have an open CC position
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change
