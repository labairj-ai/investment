# Mark-to-Market Position Valuation for NAV and Risk Limits

- **ID:** 0201
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0199

## Problem

`_nav()` and `_position_value()` in `risk_engine.py` compute position value as `qty × avg_cost` (cost basis). This means:

- A position that doubled shows the same concentration as when purchased
- A position down 50% still blocks the drawdown circuit breaker
- `MAX_POSITION_WEIGHT` and `MAX_DRAWDOWN` are measuring accounting value, not economic exposure

For the risk engine to be meaningful, concentration and drawdown must use market value.

## Proposed approach

**Add market price columns to `position_snapshots`:**
```sql
market_price   REAL   -- most recent quote
market_value   REAL   -- qty × market_price
price_as_of    TEXT   -- ISO timestamp of market_price
```

**Price refresh step** in `process_open_orders()` (before fill attempts):
```python
for symbol in active_symbols(account_id, conn):
    quote = _get_quote(symbol)
    if quote:
        mid = (quote.bid + quote.ask) / 2
        conn.execute(
            "UPDATE position_snapshots SET market_price=?, market_value=qty*?, price_as_of=? WHERE account_id=? AND symbol=?",
            (mid, mid, quote.timestamp, account_id, symbol)
        )
```

**NAV high-water mark** in `trading_accounts`:
```sql
nav_high_water REAL  -- updated whenever current NAV > prior high_water
```

**Risk engine updates:**
- `_nav()`: `cash + SUM(market_value)` — fallback to `cost` if `market_value IS NULL`
- `_position_value()`: use `market_value`
- `MAX_DRAWDOWN`: `(nav_high_water - current_nav) / nav_high_water * 100`
- `MAX_POSITION_WEIGHT`: `market_value(symbol) / nav`

**account_snapshots**: write a snapshot on each execution cycle with `cash`, `nav`, `buying_power`. Used to track peak NAV for drawdown.

## Touches

- `agent_db.py` — add `market_price`, `market_value`, `price_as_of` to `position_snapshots`; add `nav_high_water` to `trading_accounts`
- `trade_engine/risk_engine.py` — update `_nav()`, `_position_value()`, `MAX_DRAWDOWN`
- `trade_engine/execution_engine.py` — add price-refresh step in `process_open_orders()`

## Done when

- [ ] `position_snapshots` has `market_price`, `market_value`, `price_as_of` columns
- [ ] `trading_accounts` has `nav_high_water`; updated whenever NAV exceeds prior high
- [ ] Risk engine `_nav()` uses `market_value` (not `avg_cost × qty`)
- [ ] `MAX_POSITION_WEIGHT` uses market value; test: position doubles → concentration limit fires at correct weight
- [ ] `MAX_DRAWDOWN` uses `(nav_high_water - nav) / nav_high_water`; test: price drop → drawdown breaker fires
- [ ] Tests: cost basis unchanged after price move; only market_value changes
