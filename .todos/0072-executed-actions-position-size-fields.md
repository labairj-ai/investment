# Add Position Size Fields to executed_actions for Trim Fraction

- **ID:** 0072
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0070

## Problem

`_compute_scenarios()` derives the trim fraction `f` from `quantity / total_shares`, but `total_shares` is not stored in `executed_actions`, so it always falls back to `f = 0.5`. If the recommendation said "trim 20%" and the user sold 15 of 120 shares (12.5%), the outcome system models it as a 50% trim — a large error that propagates into `actual_return` and user override alpha.

## Proposed approach

- Add three columns to the `executed_actions` table:
  - `position_shares_before REAL` — position size at time of execution
  - `position_shares_after REAL` — position size after execution (can differ from before − quantity for partial-lot sales)
  - `execution_fraction REAL` — derived as `(before − after) / before` when set; stored explicitly so it survives lot-level changes
- Add a DB migration in `agent_db.migrate()` for these columns via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` (or the `_new_cols` pattern already used).
- Update `insert_executed_action()` to accept and store these fields.
- Update `_handle_agent_execute()` in `serve.py` to accept them from the request body.
- Update `_compute_scenarios()` to use `execution_fraction` when present, then `quantity / position_shares_before` as fallback, then `0.5` as last resort.

## Touches

- `agent_db.py` — migration, `insert_executed_action()`, schema
- `serve.py` — `_handle_agent_execute()` body parsing
- `agents/outcome_evaluator.py` — `_compute_scenarios()` trim fraction calculation
- `tests/test_agent_db.py` — update insert/get tests

## Done when

- [ ] `executed_actions` table has `position_shares_before`, `position_shares_after`, `execution_fraction` columns
- [ ] `insert_executed_action()` accepts and stores all three
- [ ] `_compute_scenarios()` uses stored `execution_fraction` when available
- [ ] Test: TRIM outcome with explicit fraction uses correct fraction, not 0.5 fallback
