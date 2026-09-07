# Multi-Fill Execution Aggregation

- **ID:** 0091
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

`outcome_evaluator.py` line 346 does `exec_rec = executions[0] if executions else None` with a TODO comment for multi-fill handling. A TRIM executed in two fills (30 shares @ $155, 20 shares @ $158) is evaluated as if only the first fill occurred. As execution history accumulates, this will systematically undercount the actual return on partially-executed TRIMs and mistate cash received on rolled CCs.

## Proposed approach

- Define an `ExecutionSummary` dataclass (or TypedDict) with:
  - `total_quantity`, `weighted_avg_price` (for stock actions)
  - `total_contracts`, `weighted_avg_premium` (for CC actions)
  - `total_premium_cash` (= contracts * 100 * weighted_avg_premium)
  - `execution_fraction` (from first fill, or recomputed from position_shares_before/after)
  - `first_execution_date`, `execution_date` (= date of last fill)
- Add `aggregate_executions(executions: list[dict], action: str) → ExecutionSummary` to `agent_db.py` or a new `execution_utils.py`.
- In `outcome_evaluator.py:evaluate_matured_recommendations()`, replace `executions[0]` with `aggregate_executions(executions, action)`.
- Update `_compute_scenarios()` signature: replace `exec_rec=` with `exec_summary=` and update the EXIT/TRIM/SELL_CC branches to read from `ExecutionSummary`.
- For TRIM: `actual_r = (weighted_avg_price - entry_price) / entry_price`
- For SELL_CC: `actual_r = total_premium_cash / position_value_at_rec`

## Touches

- `agents/outcome_evaluator.py` — `evaluate_matured_recommendations()`, `_compute_scenarios()`
- `agent_db.py` (or `execution_utils.py`) — `aggregate_executions()`
- `tests/test_outcome_evaluator.py` — update existing exec-rec tests; add multi-fill test
- `tests/test_lifecycle.py` — add TRIM multi-fill lifecycle scenario

## Done when

- [ ] `aggregate_executions()` exists and returns `ExecutionSummary`
- [ ] `evaluate_matured_recommendations()` uses aggregated summary, not `executions[0]`
- [ ] Test: TRIM with 2 fills produces weighted-average outcome return, not first-fill-only
- [ ] Test: SELL_CC with 2 contract fills produces correct `total_premium_cash`
- [ ] TODO comment at outcome_evaluator.py:345 is removed
