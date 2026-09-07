# Wire executed_actions Into Outcome Evaluator

- **ID:** 0070
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

`evaluate_matured_recommendations()` in `agents/outcome_evaluator.py` calls `_compute_scenarios()` with only `decision=rec.get("decision")` — it never queries `executed_actions` and never passes `exec_rec`. The `exec_rec` path inside `_compute_scenarios()` was implemented but is dead code. As a result, actual execution prices are ignored when computing `actual_return`, and `UserOverrideAlpha` and the Decision Quality model are based on estimated returns even when real execution data exists.

## Proposed approach

- For each recommendation in the matured loop, call `agent_db.get_executions_for_rec(rec["id"])` to fetch all execution rows.
- Pass the execution list (or the first/primary record) as `exec_rec=executions[0]` to `_compute_scenarios()`.
- For partial TRIM scenarios with multiple fills, accumulate a blended actual return weighted by quantity across all fills rather than using only the first record.
- Confirm `actual_is_estimated=False` only when a real execution record is present (or decision is "rejected", which is always hold).

## Touches

- `agents/outcome_evaluator.py` — `evaluate_matured_recommendations()` loop
- `tests/test_outcome_evaluator.py` — add test with a seeded execution record

## Done when

- [ ] `evaluate_matured_recommendations()` queries `executed_actions` for each recommendation before calling `_compute_scenarios()`
- [ ] When an execution record exists, `actual_return` is computed from `execution_price`, not estimated
- [ ] `actual_is_estimated` is `False` only when a real execution or a confirmed "rejected" decision is present
- [ ] New test: seeded execution record produces non-estimated `actual_return` matching expected math
