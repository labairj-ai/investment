# PRE_FILL Risk Must Evaluate Remaining Quantity, Not Original Order Quantity

- **ID:** 0230
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0229

## Problem

`process_open_orders()` calls `risk_evaluate(intent, ...)` for PRE_FILL decisions, but `intent.quantity` is the original order quantity. Inside `evaluate()`, `trade_qty = intent.quantity` (`risk_engine.py:270`) and `trade_cost = trade_qty * intent.limit_price`. For a partially filled order (e.g., 60 of 100 shares filled), this evaluates a $10,000 trade when only $4,000 of exposure remains. This can incorrectly cancel valid partial fills on cash, position-weight, daily-notional, and sell-coverage rules.

A partial SELL is especially problematic: 40 remaining shares will be evaluated as 100, making the position look like it can't cover the sell even though 60 already settled.

## Proposed approach

- Add `remaining_quantity: Optional[float] = None` parameter to `risk_engine.evaluate()`.
- When `remaining_quantity` is provided, use it in place of `intent.quantity` for the following rules: SUFFICIENT_CASH, MAX_NEW_POSITION_PCT, MAX_SINGLE_POSITION_PCT, MAX_DAILY_NOTIONAL, SELL_HAS_POSITION (coverage check uses remaining sell qty).
- Rules that should still use original intent quantity: VALID_SIDE_FOR_INSTRUMENT, INTENT_NOT_EXPIRED, TRADING_ENABLED — these are structural and not quantity-sensitive.
- In `process_open_orders()` (`execution_engine.py:390`): compute `remaining = order.quantity - (order.fill_qty or 0.0)` and pass `remaining_quantity=remaining` to `risk_evaluate(...)`.
- Tests: partial BUY (60/100 filled): PRE_FILL on remaining 40 passes cash/weight/notional checks that would fail on 100. Partial SELL: remaining 40 passes sell-coverage check even though position only holds 40.

## Touches

- `trade_engine/risk_engine.py` — `evaluate()`, rules SUFFICIENT_CASH, MAX_NEW_POSITION_PCT, MAX_SINGLE_POSITION_PCT, MAX_DAILY_NOTIONAL, SELL_HAS_POSITION
- `trade_engine/execution_engine.py` — `process_open_orders()` call to `risk_evaluate`
- `tests/test_trade_engine.py` — partial BUY and SELL PRE_FILL tests

## Done when

- [ ] `evaluate()` accepts `remaining_quantity` and uses it for quantity-sensitive rules
- [ ] `process_open_orders()` passes `remaining_quantity = order.quantity - order.fill_qty`
- [ ] Partial BUY PRE_FILL uses remaining qty for cash and position-weight checks
- [ ] Partial SELL PRE_FILL uses remaining qty for sell-coverage check
- [ ] Tests for both BUY and SELL partial-fill risk scenarios pass
