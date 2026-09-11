# Fix Roll Suggester to Rank by cc_alpha and Match Roll Type

- **ID:** 0138
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

`_suggest_next_call()` in `covered_call_rec.py` (line ~939) ranks candidate roll contracts by `exec_prem / strike * 100` (a raw yield proxy) rather than `cc_alpha` (premium minus expected upside surrendered). This is inconsistent with the main `analyze()` pipeline. A contract with high yield and negative `cc_alpha` can surface as the top roll suggestion even though the main screener would reject it.

Additionally, the function uses a fixed 14-75 DTE window regardless of roll type: ROLL_OUT needs expiry past the risk event date; ROLL_UP should prefer the existing expiry cycle; ROLL_UP_AND_OUT needs a later expiry than the current one as a hard floor. The suggestion is displayed on the dashboard as the recommended roll target.

## Proposed approach

- Add `cc_alpha` computation to `_suggest_next_call()` (pass in `hv_forecast` as a parameter) and replace `score = exec_prem / s * 100` with cc_alpha.
- Accept a `roll_type` parameter and optional `risk_event_date` / `existing_expiry` to drive the expiry filter:
  - `roll_out`: expiry must be > risk_event_date (or > existing_expiry if no event date known)
  - `roll_up`: prefer contracts near existing expiry
  - `roll_up_and_out`: expiry must be strictly > existing_expiry
- Wire the `roll_type` from `_analyze_roll()` (which already knows the action) through to the call site.

## Touches

- `covered_call_rec.py` — `_suggest_next_call()` (~lines 910-957) and its call sites in `evaluate_open_position()`
- `agents/covered_call_agent.py` — `_analyze_roll()` to pass roll_type through

## Done when

- [ ] `_suggest_next_call()` accepts `roll_type` and ranks by cc_alpha
- [ ] ROLL_OUT suggestions always clear the risk event date
- [ ] ROLL_UP suggestions prefer the existing expiry cycle
- [ ] Existing tests pass; spot-check live ticker yields cc_alpha-positive suggestion
