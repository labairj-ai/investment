# Expand CC Management Recommendation Dependencies

- **ID:** 0095
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** none

## Problem

CC management recommendations (HOLD_CALL, BUY_TO_CLOSE, ROLL_OUT, ROLL_UP, ROLL_UP_AND_OUT, ALLOW_ASSIGNMENT) currently only carry a single PRICE dependency with 3% tolerance. This means a HOLD_CALL recommendation remains valid even after IV spikes, the option mark doubles, earnings enters the window, delta jumps, or the call is externally closed — none of which move the underlying stock 3%. The recommendation silently stays open and misleads the decision queue.

## Proposed approach

- In `covered_call_agent.py`, extend the `dependencies` list for all management actions to include:
  - `CC_POSITION_STATE` — invalidate if the CC position is closed, expired, or assigned outside the agent
  - `OPTION_MARK` — invalidate if current mark has moved ≥20% from the mark at rec time (captured in payload)
  - `OPTION_IV` — invalidate if IV rank has shifted ≥15 points
  - `OPTION_LIQUIDITY` — invalidate if bid/ask spread has widened beyond an acceptable threshold
  - `OPTION_EXPIRATION` — invalidate when DTE crosses key thresholds (e.g., enters the final 7-DTE management window)
  - `EARNINGS_DATE` — invalidate if an earnings event has entered the DTE window since rec was created
- For roll recommendations (ROLL_OUT, ROLL_UP, ROLL_UP_AND_OUT), persist the proposed replacement contract (strike, expiration, target premium) in the payload and add a dependency that invalidates if either the BTC leg or the STO leg has moved materially
- Add `_check_option_mark`, `_check_option_iv`, `_check_option_expiration` handlers in `dependency_checker.py`

## Touches

- `agents/covered_call_agent.py`
- `agents/dependency_checker.py`
- `agent_db.py` (dependency type constants if enumerated)

## Done when

- [ ] HOLD_CALL recommendations carry at minimum PRICE + CC_POSITION_STATE + OPTION_MARK + OPTION_EXPIRATION dependencies
- [ ] Roll recommendations also carry a dependency on the proposed replacement contract parameters
- [ ] `dependency_checker.py` handles the new dependency types without falling through to the "unknown type → supersede" fallback
- [ ] Unit tests in `tests/test_dependency_checker.py` cover each new dependency type with a fixture that triggers invalidation
- [ ] Regression: existing PRICE and CC_POSITION_STATE dependency checks still pass
- [ ] Manual web check: Decision queue shows invalidated CC management recs as superseded after an option mark move, not stale-open
