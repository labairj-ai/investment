# Fix ALLOW_ASSIGNMENT Priority and DTE Gate in CC Management Engine

- **ID:** 0139
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

Two related logic gaps in `_decide_mgmt_action()` (`agents/covered_call_agent.py`, lines ~228-240):

**1. ROLL_OUT overrides ALLOW_ASSIGNMENT for risk events on deeply profitable positions.**
The function returns `ROLL_OUT` whenever `has_avoid=True`, before evaluating position profitability. For a position that is already deeply ITM (stock 5%+ above strike) with upcoming earnings, ALLOW_ASSIGNMENT is often better: the profit is locked in, expiration ITM is near-certain, and rolling concentrates risk into the earnings uncertainty window.

**2. ALLOW_ASSIGNMENT DTE gate (`dte <= 14`) is too narrow.**
The management trigger fires at 21 DTE. A stock that is deeply ITM at 20 DTE faces the same economics as at 14 DTE. The 14-day threshold was a conservative first pass and should be at least 21 days, or gated on a profitability condition (e.g., `pct_captured >= 50`).

## Proposed approach

For gap 1, check deeply_itm before the has_avoid branch:
- `if deeply_itm and has_avoid: return "ALLOW_ASSIGNMENT"` before the existing `if has_avoid: return "ROLL_OUT"`

For gap 2, widen the DTE threshold from 14 to 21, or add a capture-percentage condition:
- `if deeply_itm and (dte <= 21 or (pct_captured or 0) >= 50): return "ALLOW_ASSIGNMENT"`

Update `_eval_open_economics()` reason strings in `covered_call_rec.py` to match.

## Touches

- `agents/covered_call_agent.py` — `_decide_mgmt_action()` (~lines 213-240)
- `covered_call_rec.py` — `_eval_open_economics()` (~lines 847-907)

## Done when

- [ ] A deeply ITM position with an upcoming earnings event receives ALLOW_ASSIGNMENT, not ROLL_OUT
- [ ] ALLOW_ASSIGNMENT fires for deeply ITM positions at up to 21 DTE
- [ ] Test case added covering deeply_itm + has_avoid scenario
- [ ] Existing tests pass
