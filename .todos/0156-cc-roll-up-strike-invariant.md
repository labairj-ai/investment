# Add Explicit Strike-Up Invariant to ROLL_UP and ROLL_UP_AND_OUT

- **ID:** 0156
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

`_suggest_next_call()` in `covered_call_rec.py` filters candidate contracts with:

    calls = calls[calls["strike"] >= min_strike]

For ROLL_UP and ROLL_UP_AND_OUT, the intent is specifically to move to a HIGHER strike to relieve assignment pressure or capture more upside. However, the current code relies on `min_strike` passed by the caller to enforce this -- there is no guard inside `_suggest_next_call()` itself.

If the caller passes min_strike <= existing_strike (e.g., due to a bug or new call path), a "ROLL_UP" could select a same-strike or lower-strike contract, which is economically nonsensical (not a real roll-up -- it's just re-entering the same trade or going deeper ITM).

The function should be impossible to misuse: the invariant should be enforced at the point of contract selection.

## Proposed approach

Add `existing_strike: float | None = None` parameter to `_suggest_next_call()`. Inside the candidate loop, when `roll_type in ("ROLL_UP", "ROLL_UP_AND_OUT")`, reject any contract where `strike <= existing_strike`:

    if roll_type in ("ROLL_UP", "ROLL_UP_AND_OUT"):
        if existing_strike is not None and strike <= existing_strike:
            continue

Also add the inverse for completeness (optional, but defensively useful):
    if roll_type == "ROLL_OUT":
        # same strike or slightly lower is acceptable (pure time roll)
        pass

Update callers in `covered_call_agent.py` / `_analyze_roll()` to pass `existing_strike`.

## Touches

- `covered_call_rec.py` -- `_suggest_next_call()` signature + strike invariant guard
- `agents/covered_call_agent.py` -- `_analyze_roll()` to pass `existing_strike`
- `tests/test_covered_call_rec.py` (if it exists) -- test that ROLL_UP rejects lower-strike candidates

## Done when

- [ ] `_suggest_next_call()` accepts `existing_strike` parameter
- [ ] ROLL_UP / ROLL_UP_AND_OUT with a candidate strike <= existing_strike is filtered out
- [ ] Caller passes existing_strike from the open position payload
- [ ] Existing tests pass
