# Fix Post-Assignment CC Return for Post-Expiry Horizons

- **ID:** 0113
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** 0106

## Problem

When a SELL_CC expires with the stock above the strike (assigned path, `cc_assignment_state = 'assigned'`), the outcome evaluator currently sets `actual_r` and `recommended_path_return` to `0.0` for the `30d_post` and `90d_post` horizons. This is economically wrong — 0.0 implies the strategy lost everything, when shares were actually called away at the strike and the investor holds cash. The error systematically understates CC strategy performance in the agent alpha calculations used to compare CC vs HOLD and CC vs SPY.

## Proposed approach

- At the `at_expiry` horizon, compute and store the assignment return: `r_assign = (K − entry_price + premium) / entry_price`.
- For `30d_post` and `90d_post` on the assigned path, carry `r_assign` forward as both `actual_r` and `recommended_path_return` (cash sitting idle earns 0 additional return, so the post-expiry value equals the at-expiry value).
- The `hold_return` and `benchmark_return` columns for these horizons already reflect what holding the stock or SPY would have returned over the full period — those are correct and should not change.
- Update `_compute_scenarios()` in `outcome_evaluator.py` to read `cc_assignment_state` from the DB when evaluating post-expiry CC horizons, and branch accordingly instead of defaulting to `0.0`.
- Add unit tests: assigned post-expiry actual_r equals at_expiry assignment return; expired post-expiry actual_r uses the existing price-drift formula.

## Touches

- `agents/outcome_evaluator.py`
- `tests/test_outcome_evaluator.py`

## Done when

- [ ] `30d_post` and `90d_post` `actual_r` on the assigned path equals `(K − entry + premium) / entry`, not `0.0`
- [ ] `recommended_path_return` for assigned post-expiry horizons matches the same locked value
- [ ] Expired post-expiry path is unchanged
- [ ] Unit tests cover both assigned and expired post-expiry branches
