# Model Actual CC Execution Outcome Separate from Recommended Path

- **ID:** 0073
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0070

## Problem

When a SELL_CC recommendation is acted on, the executed premium, strike, and contract count from `executed_actions` are not used to compute `actual_return` in `_compute_scenarios()`. Instead the actual path falls into the generic non-EXIT branch. This means the system cannot distinguish between "agent recommended $180 strike / $2.40 premium, user sold $185 strike / $1.80 premium" — a behaviorally important override that could indicate a systematic preference for more OTM calls.

## Proposed approach

- Add a CC-specific actual-return branch in `_compute_scenarios()` when `action == "SELL_CC"` and an `exec_rec` is present.
- Use `exec_rec["execution_price"]` as actual premium, `exec_rec["strike"]` and `exec_rec["expiration"]` for the actual contract.
- Compute actual CC return as: `(min(S_T, K_actual) − S_0 + premium_actual) / S_0`.
- Set `actual_is_estimated = False` when all required fields are present.
- Consider linking `executed_actions` to `cc_positions` via a foreign key or a `cc_position_id` column so roll history, buyback price, and assignment status can be incorporated later.
- Open question: should a rolled CC be modeled as close + reopen (two execution rows) or as a single row with roll metadata?

## Touches

- `agents/outcome_evaluator.py` — `_compute_scenarios()` CC actual branch
- `agent_db.py` — potentially add `cc_position_id` to `executed_actions`
- `tests/test_outcome_evaluator.py` — add CC execution outcome test

## Done when

- [ ] `_compute_scenarios()` computes `actual_return` from actual premium/strike when `exec_rec` is present for a SELL_CC
- [ ] `actual_is_estimated = False` when real execution data is used
- [ ] Test: recommended $180 strike vs executed $185 strike produces different `actual_return` vs `cc_strategy_return`
