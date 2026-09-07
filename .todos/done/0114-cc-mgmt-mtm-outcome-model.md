# Redesign CC-Management Outcome Evaluation Around MTM Starting State

- **ID:** 0114
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** 0113

## Problem

The current outcome evaluator credits CC management decisions (HOLD_CALL, BUY_TO_CLOSE, ROLL_*) with option premium that was actually collected at the original SELL_CC date, not at the management decision date. For ALLOW_ASSIGNMENT, `actual_r = (K - entry_price + original_premium) / entry_price` mixes the old premium with the current stock price. For ROLLs, the new short call is not tracked through its own expiration — the formula only captures the net roll credit but ignores whether the new leg expires ITM or OTM. This makes Decision Quality comparisons unreliable and can attribute prior SELL_CC gains to later management decisions.

## Proposed approach

Correct baseline: evaluate the management decision from the MTM state at rec date.
- `ALLOW_ASSIGNMENT`: actual_r = `(K - S_rec) / S_rec` where S_rec is stock price at management rec date (stock locked at K). Drop original_premium from the management-decision return; it already belongs to the SELL_CC outcome row.
- `ROLL_*`: after writing the BTC+STO at_expiry row, continue evaluating the new leg through its own expiry (30d/90d_post equivalent for the new contract). This requires persisting the new call's details (new_strike, new_expiry) so the evaluator can look up S at new_expiry and branch assigned/expired.
- `HOLD_CALL`: current model (actual = hold_r) is correct from MTM perspective.
- `BUY_TO_CLOSE`: current model (actual = hold_r + (orig_premium - btc_exec) / entry) is approximately correct but orig_premium here should be the current option mark at rec date, not the original premium — track via `option_quote_snapshots`.
- Long term: implement a CC trade state machine that stores per-contract open/close states and evaluates each leg independently.

## Touches

- `agents/outcome_evaluator.py`
- `agent_db.py` (possibly new column to persist new_strike/new_expiry for roll legs)
- `tests/test_outcome_evaluator.py`

## Done when

- [ ] ALLOW_ASSIGNMENT actual_r does not include original SELL_CC premium
- [ ] ROLL at_expiry horizon caps upside at new_strike when stock is assigned
- [ ] ROLL 30d/90d post follow same assigned/expired branching as SELL_CC post-expiry
- [ ] Unit tests cover ROLL at_expiry assigned and expired paths
