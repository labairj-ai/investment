# Add Open-Order Reservation Accounting to Risk Engine

- **ID:** 0211
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`risk_engine.py:_daily_notional()` queries only `fills` (settled trades). A WORKING BUY order for $1,500 is invisible — the risk engine's next intent evaluates as if that capital is still available. With `max_daily_notional_pct=20%` on a $10k account ($2,000 limit), two concurrent $1,500 BUY intents can both pass and both fill, consuming $3,000. The same gap exists for available cash (rule 7), position concentration (rule 8), and sell coverage (rule 12). This is the biggest architectural gap before external broker integration.

## Proposed approach

Add three helpers to `risk_engine.py`:

```python
def _open_buy_notional(account_id: str, conn: sqlite3.Connection) -> float:
    """Sum of (quantity * limit_price) for all open BUY/BUY_TO_CLOSE orders."""
    row = conn.execute(
        """SELECT COALESCE(SUM((quantity - fill_qty) * limit_price), 0) as t
           FROM orders
           WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')
             AND side IN ('BUY','BUY_TO_CLOSE')""",
        (account_id,),
    ).fetchone()
    return float(row["t"] or 0)

def _open_sell_qty(account_id: str, symbol: str, conn: sqlite3.Connection) -> float:
    """Sum of remaining sell quantity for open SELL orders on a symbol."""
    row = conn.execute(
        """SELECT COALESCE(SUM(quantity - fill_qty), 0) as t
           FROM orders
           WHERE account_id=? AND symbol=? AND state IN ('WORKING','PARTIALLY_FILLED')
             AND side IN ('SELL','SELL_TO_OPEN')""",
        (account_id, symbol),
    ).fetchone()
    return float(row["t"] or 0)
```

Update risk checks to use reservation-adjusted values:
- **Rule 7 SUFFICIENT_CASH**: `available_cash = account.current_cash - open_buy_notional`; apply `min_cash` floor against `available_cash`
- **Rule 8 MAX_POSITION_WEIGHT**: projected weight uses `current_pos_value + open_buy_notional_for_symbol + trade_cost` as numerator
- **Rule 10 MAX_DAILY_NOTIONAL**: `daily_total = _daily_notional() + _open_buy_notional() + trade_cost` (proposed trade on top of reserved)
- **Rule 12 SELL_QUANTITY_COVERED**: `available_qty = current_pos_qty - _open_sell_qty(symbol)`

Precompute `open_buy_notional = _open_buy_notional(account.account_id, conn)` once at the top of `evaluate()` alongside `nav` and `trade_cost` to avoid repeated queries.

## Touches

- `trade_engine/risk_engine.py` — new helpers, updated rules 7, 8, 10, 12
- `tests/test_trade_engine.py` — new `TestReservationAccounting` tests

## Done when

- [ ] Two concurrent $1,500 BUY intents: second fails MAX_DAILY_NOTIONAL when limit is $2,000
- [ ] Open BUY order for symbol X reduces available cash for a second BUY on symbol Y
- [ ] Open SELL order for 50 shares blocks a second SELL of 60 shares from the same 80-share position (only 30 free)
- [ ] BUY weight projection includes open buy notional for the same symbol
- [ ] `_open_buy_notional` returns 0.0 when no open orders exist (no regression)
- [ ] All 391 existing tests still pass
