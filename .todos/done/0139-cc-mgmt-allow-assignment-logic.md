# Fix ALLOW_ASSIGNMENT Logic in CC Management Engine via assignment_eligible()

- **ID:** 0139
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

`_decide_mgmt_action()` (`agents/covered_call_agent.py`, lines ~228-240) uses two blunt heuristics for the assignment/roll-out decision:

1. `if has_avoid: return "ROLL_OUT"` — fires unconditionally for any risk event, even when the position is already deeply ITM with near-certain assignment, concentrating risk into the very earnings uncertainty window the roll is trying to avoid.
2. `if deeply_itm and dte <= 14: return "ALLOW_ASSIGNMENT"` — `deeply_itm` is a simple flag (stock 5%+ above strike), not a probabilistic check. The 14 DTE threshold is arbitrary and misses economically identical situations at 15-20 DTE.

Neither branch accounts for thesis-level exit criteria (is this an acceptable sale price?), tax lot status (does assignment trigger a large short-term gain?), or portfolio constraints (is this position a core anchor that shouldn't be assigned?).

## Proposed approach

Replace both branches with a single gate function:

```python
def assignment_eligible(ticker, rec, policy, db) -> tuple[bool, str]:
```

Returns `True` when ALL of:
1. **Real-world ITM probability > 80-90%** — use the real-world drift model already in `covered_call_rec.py` (same model used for cc_alpha), not just a `deeply_itm` flag
2. **Remaining extrinsic < threshold** (e.g., < 1% of stock price) — `remaining_extrinsic` already present in action_payload
3. **Acceptable sale price** — if `acceptable_assignment_min_price` is set in cc_policy JSON, check `current_price >= floor`; default True if unset (add this 7th field to `_CC_POLICY_DEFAULTS`)
4. **No short-term gain concern** — query cost lots via `agent_db`; if position < 365 days old and ST gain would be large, prefer ROLL_OUT to defer the gain (soft check)
5. **No portfolio constraint** — position is not a core portfolio anchor that concentration targets require holding

New `_decide_mgmt_action()` priority: cap ≥ 80 → BUY_TO_CLOSE → `if assignment_eligible(...): ALLOW_ASSIGNMENT` → roll branches. This removes both the unconditional `has_avoid → ROLL_OUT` and the `deeply_itm + dte ≤ 14` shortcut. `has_avoid` becomes an input to `assignment_eligible()` (risk event raises the ITM probability threshold required) rather than a direct action gate.

## Touches

- `agents/covered_call_agent.py` — new `assignment_eligible()` helper; updated `_decide_mgmt_action()` (~lines 213-240); `_CC_POLICY_DEFAULTS` (~line 108) gains `acceptable_assignment_min_price: None`
- `covered_call_rec.py` — `_eval_open_economics()` reason strings (~lines 847-907)
- `agent_db.py` — cost lot query for ST gain check (may already exist for tax agent)

## Done when

- [ ] `assignment_eligible()` function implemented with all 5 checks
- [ ] Deeply ITM position with upcoming earnings → ALLOW_ASSIGNMENT when all 5 checks pass
- [ ] Deeply ITM position with large short-term gain → ROLL_OUT
- [ ] Position with `acceptable_assignment_min_price` set in cc_policy → respects floor
- [ ] Test cases covering each gate condition; existing tests pass
