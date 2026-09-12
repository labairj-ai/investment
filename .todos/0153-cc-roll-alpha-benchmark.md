# Correct Incremental Roll Alpha: Compare vs Remaining Old-Call Alpha

- **ID:** 0153
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

`_suggest_next_call()` in `covered_call_rec.py` now ranks candidates by incremental roll alpha computed as:

    (new_cc_alpha - existing_call_mark) / NAV

The problem: `existing_call_mark` is the current market price of the old short call, not its expected economic value going forward. If the old call is deep ITM with a large expected payoff, the mark understates the true future liability, and the formula overstates the attractiveness of rolling.

Example:
- Old call mark = $5
- Expected old-call payoff (under real-world drift) = $8 -> old remaining alpha = -$3
- New call alpha = +$2
- Economically, rolling is attractive: gain $2, give up -$3 liability = net +$5
- Current formula: $2 - $5 = -$3 -> incorrectly REJECTS the roll

The correct benchmark is the expected future alpha of the existing short call (which may be negative if it is deep ITM), not just its mark.

## Proposed approach

Add a helper `_remaining_call_alpha(existing_position, vol_model)` that computes the expected alpha of the existing call from today to its expiration using the same real-world drift model used for cc_alpha:

    existing_alpha = existing_call_premium_received - E[max(S_T - K_old, 0)]

where the expectation is under real-world drift from the current date to the old expiry.

Then replace the ranking formula with:

    incremental_alpha = new_cc_alpha - max(existing_alpha, 0)

(floor at zero -- if existing call is already profitable and you close it, you give up that remaining value)

Alternatively:

    incremental_alpha = new_cc_alpha - existing_alpha

where existing_alpha can be negative (deep ITM call is a liability), making rolling even more attractive when the existing call is a drag.

Normalize by NAV for a percentage figure. Reject candidates where incremental_alpha <= 0.

## Touches

- `covered_call_rec.py` -- `_suggest_next_call()` ranking formula; new `_remaining_call_alpha()` helper using existing vol model

## Done when

- [ ] `_remaining_call_alpha()` computes expected future value of existing call under real-world drift
- [ ] `incremental_alpha = new_cc_alpha - existing_alpha` (negative existing_alpha makes rolling more attractive)
- [ ] Deep-ITM old call (expected payoff > mark) scenario now correctly favors a roll
- [ ] Existing tests pass
