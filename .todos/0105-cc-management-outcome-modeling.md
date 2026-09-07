# Add Outcome Evaluator Support for CC Management Actions

- **ID:** 0105
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0104

## Problem

`outcome_evaluator.py` declares `CC_ACTIONS = {"SELL_CC"}` and has no outcome modeling for `BUY_TO_CLOSE`, `ROLL_OUT`, `ROLL_UP`, `ROLL_UP_AND_OUT`, `ALLOW_ASSIGNMENT`, or `HOLD_CALL`. The system can now recommend and record all of these actions, but it cannot evaluate whether the recommendation was correct. Without outcome rows for these actions, `AgentAlpha_vs_Hold` and `UserOverrideAlpha` are computed only on the initial CC sale, not on subsequent management decisions — making the CC agent's performance statistics incomplete.

## Proposed approach

- Add `CC_MANAGEMENT_ACTIONS = {"BUY_TO_CLOSE", "ROLL_OUT", "ROLL_UP", "ROLL_UP_AND_OUT", "ALLOW_ASSIGNMENT", "HOLD_CALL"}`.
- Outcome models per action (all using exec_price from the relevant `executed_actions` row):
  - **BUY_TO_CLOSE**: `actual_r = (original_premium - btc_price) / entry_price + hold_r_from_exec_date`; agent_r is the same formula using rec-date option mark.
  - **ALLOW_ASSIGNMENT**: `actual_r = (K - entry_price + original_premium) / entry_price`; position ends at expiry so 30d/90d post horizons show cash (return = 0 from assignment proceeds).
  - **ROLL**: `actual_r = btc_gain + new_premium`; agent_r uses rec-date marks for both legs; follow-on position (new call) is tracked as a linked SELL_CC outcome seeded from the roll STO leg.
  - **HOLD_CALL**: `actual_r = hold_r` (no action taken); agent_r is the counterfactual BTC scenario at rec-date mark.
- Horizons: equity horizons `1w/1m/3m` measured from recommendation date for BTC/HOLD_CALL; `at_expiry/30d_post/90d_post` for ALLOW_ASSIGNMENT and ROLL.
- Add a `_compute_cc_management_returns()` helper; route from `_compute_returns()` by action.

## Touches

- `agents/outcome_evaluator.py` — `CC_ACTIONS`, new `CC_MANAGEMENT_ACTIONS`, `_compute_cc_management_returns()`, `_compute_returns()` routing
- `tests/test_outcome_evaluator.py` (create if absent) — unit tests per action type
- `tests/test_lifecycle.py` — add lifecycle scenario: ROLL recommendation accepted+executed, check outcome row written for both legs

## Done when

- [ ] `CC_MANAGEMENT_ACTIONS` defined; each action type routes to a dedicated outcome formula.
- [ ] Unit test: BUY_TO_CLOSE with known btc_price and known horizon price produces correct `actual_r` and `agent_r`.
- [ ] Unit test: ALLOW_ASSIGNMENT at a strike above entry_price shows `actual_r` matching `(K - S0 + premium) / S0`; 30d/90d post horizons show 0 (cash, no further price exposure).
- [ ] Unit test: ROLL records outcome rows for both the BTC leg and the new STO leg.
- [ ] Unit test: HOLD_CALL produces `actual_r = hold_r` and `agent_r` reflects the counterfactual BTC mark.
- [ ] No regression on existing SELL_CC outcome tests.
- [ ] Full pytest suite passes.
- [ ] On optiplex: run the evaluator against any existing BUY_TO_CLOSE or ALLOW_ASSIGNMENT recommendation and confirm an outcome row is written to `recommendation_outcomes`.
