# Multi-Leg Execution Model for CC Rolls

- **ID:** 0101
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** low
- **Depends:** 0098

## Problem

A roll recommendation (ROLL_OUT, ROLL_UP, ROLL_UP_AND_OUT) is a two-legged trade — a BUY_TO_CLOSE on the existing call and a SELL_TO_OPEN on the replacement. The current execution model treats it as a single `executed_actions` row with one fill price. This makes it impossible to accurately measure: actual net credit/debit, per-leg fill quality, or whether the roll improved the position. CC performance attribution and decision-quality learning for rolls are therefore unreliable.

## Proposed approach

- Add an `execution_group_id` column to `executed_actions` (nullable integer)
- When recording a roll execution, create two rows under the same `execution_group_id`:
  - Leg 1: BTC — action='BUY_TO_CLOSE', execution_price=debit paid, strike/expiry of existing call
  - Leg 2: STO — action='SELL_CC', execution_price=premium received, strike/expiry of new call
- The `execution_group_id` links both legs to the original roll recommendation (`recommendation_id`)
- Net credit = STO premium − BTC debit; store this as a derived field or compute it at reporting time from the two rows
- Update `aggregate_executions()` in `agent_db.py` to handle multi-leg groups: return both legs and a computed net summary
- Update outcome evaluator to use the net credit for ROLL outcomes
- The UI execution form for rolls should accept two sets of fill fields (one per leg) rather than a single price

## Touches

- `agent_db.py` (`executed_actions` schema, `aggregate_executions`, `insert_executed_action`)
- `execution_validation.py` (validate multi-leg consistency: net credit > 0 for typical roll)
- `serve.py` (`_handle_agent_execute` — accept and route multi-leg payload)
- `agents/outcome_evaluator.py` (use net credit for ROLL outcome)
- `generate_dashboard.py` (execution form for roll actions)

## Done when

- [ ] `executed_actions` has `execution_group_id` column
- [ ] Roll execution API accepts two-leg payload and creates two rows with matching `execution_group_id`
- [ ] `aggregate_executions()` returns net credit for rolls computed from both legs
- [ ] Outcome evaluator uses net credit for ROLL `actual_return`
- [ ] Unit test: roll execution creates 2 rows, net credit computed correctly
- [ ] Unit test: validation rejects a roll where BTC debit > STO premium without explicit override
- [ ] Dashboard roll execution form collects per-leg fill prices
- [ ] Regression: single-leg executions (SELL_CC, BUY_TO_CLOSE alone) still work correctly
