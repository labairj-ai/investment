# Include Open SELL Notional in Daily Turnover Reservation

- **ID:** 0223
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

Risk rule 10 (MAX_DAILY_NOTIONAL) computes `daily_total = filled_notional + _open_buy_notional() + trade_cost` but ignores open SELL order notional. A $1,500 WORKING SELL order plus a new $1,500 SELL both pass a $2,000 daily limit because the open sell's notional is invisible. Total daily turnover can exceed the policy limit.

## Proposed approach

1. Add `_open_sell_notional(account_id, conn) -> float` to `risk_engine.py`:
   `SELECT SUM((COALESCE(quantity,0) - COALESCE(fill_qty,0)) * COALESCE(limit_price,0)) FROM orders WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED') AND side IN ('SELL','SELL_TO_OPEN')`.
2. Update rule 10: `open_gross = _open_buy_notional() + _open_sell_notional()`, then `daily_total = filled_notional + open_gross + trade_cost`.
3. Rule 7 (SUFFICIENT_CASH) stays buy-side only — sells don't consume cash.

## Touches

- `trade_engine/risk_engine.py` — new `_open_sell_notional()`, rule 10 logic
- `tests/test_trade_engine.py` — WORKING SELL + new SELL exceeds limit test

## Done when

- [ ] `_open_sell_notional()` returns correct gross sell commitment for open orders
- [ ] Rule 10 includes open sell notional in daily total
- [ ] WORKING SELL $1,500 + new SELL $1,500 against $2,000 limit → REJECTED
- [ ] Rule 7 (SUFFICIENT_CASH) unchanged — still buy-side only
- [ ] All existing tests pass
