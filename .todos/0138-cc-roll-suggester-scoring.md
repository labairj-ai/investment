# Fix Roll Suggester to Rank by cc_alpha and Match Roll Type

- **ID:** 0138
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** high
- **Depends:** none

## Problem

`_suggest_next_call()` in `covered_call_rec.py` (line ~939) ranks candidate roll contracts by `exec_prem / strike * 100` (a raw yield proxy). This answers the wrong question. The real economic question is: "Is replacing the existing short call with this new contract worth more than simply buying back the existing one?" A contract with high yield but low cc_alpha relative to the existing call's remaining value creates negative incremental value even though raw yield looks attractive.

Additionally, the function uses a fixed 14-75 DTE window regardless of roll type. The roll-type expiry constraints are preferences instead of hard filters: a ROLL_OUT that doesn't clear the risk event date and a ROLL_UP_AND_OUT that doesn't push out expiry both defeat the purpose of the roll action.

## Proposed approach

Replace the yield proxy with **incremental roll alpha**:
```
incremental_roll_alpha = (new_cc_alpha - existing_short_call_remaining_value) / NAV
```
- `new_cc_alpha` = `exec_prem - E[max(S_T - K, 0)]` under real-world drift (same formula as `analyze()`)
- `existing_short_call_remaining_value` = `current_mark` from action_payload (already present)
- `NAV` = `entry_price - btc_mark` (already computed in `_analyze_roll()`, pass through)

**Hard eligibility rules per roll type** — contracts that fail are excluded entirely, not softly penalized:
- `ROLL_OUT`: candidate expiry MUST be > risk_event_date; if no risk event, MUST be > existing_expiry
- `ROLL_UP`: candidate expiry MUST be within ±1 cycle of existing expiry
- `ROLL_UP_AND_OUT`: candidate expiry MUST be strictly > existing_expiry

Wire `roll_type`, `nav`, `current_mark` (existing call), and `risk_event_date` / `existing_expiry` from `_analyze_roll()` into `_suggest_next_call()`. Keep the existing `cc_alpha > 0` minimum bar as a hard gate — never suggest a negative-alpha replacement.

## Touches

- `covered_call_rec.py` — `_suggest_next_call()` (~lines 910-957) and its call sites in `evaluate_open_position()`
- `agents/covered_call_agent.py` — `_analyze_roll()` to pass roll_type through

## Done when

- [ ] `_suggest_next_call()` ranks by incremental roll alpha `(new_cc_alpha - existing_call_mark) / NAV`
- [ ] ROLL_OUT candidates that don't clear risk event date are hard-rejected (not just ranked lower)
- [ ] ROLL_UP candidates outside ±1 cycle of existing expiry are hard-rejected
- [ ] ROLL_UP_AND_OUT candidates with expiry ≤ existing expiry are hard-rejected
- [ ] Existing tests pass; spot-check live ticker yields positive incremental alpha suggestion
