# Fail Closed on Missing or Stale Market Data

- **ID:** 0200
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0199

## Problem

When `_get_quote()` fails (Yahoo down, DNS error, malformed response), `execution_engine.py` currently synthesizes a fallback:

```python
Quote(bid=intent.limit_price, ask=intent.limit_price)
```

Because the limit test is `ask <= limit` for buys, this guarantees a fill at exactly the limit price. A network outage becomes a fabricated execution — the exact opposite of fail-closed behavior.

## Proposed approach

Remove the fallback `Quote` entirely.

**No quote → no fill.** Order remains `WORKING`. Log `market_data_status=UNAVAILABLE` on the order row.

New column on `orders`:
```sql
market_data_status TEXT  -- 'ok' | 'unavailable' | 'stale'
```

In `process_open_orders()`:
```python
quote = _get_quote(symbol)
if quote is None:
    _mark_order_data_unavailable(order, conn)
    continue  # skip fill attempt entirely
fill = broker.attempt_fill(order, quote)
```

**Quote freshness check**: Add `quote_age_seconds` check in `attempt_fill()` — if `quote.timestamp` is more than `policy.halt_on_data_stale_minutes() * 60` seconds old, treat as unavailable.

**Halt escalation** (future): if an account has had `market_data_status=unavailable` for more than N consecutive cycles, set `trading_accounts.trading_enabled=0` (circuit breaker).

For the `DATA_FRESHNESS` risk rule: align it to use the same freshness threshold as the fill path.

## Touches

- `trade_engine/execution_engine.py` — remove fallback quote, add unavailability handling
- `trade_engine/shadow_broker.py` — add quote age check in `attempt_fill()`
- `agent_db.py` — add `market_data_status` column to `orders`

## Done when

- [ ] `_get_quote()` returns None → order stays WORKING, `market_data_status='unavailable'`, no fill written
- [ ] Quote with timestamp > stale threshold → treated same as None
- [ ] Removing the fallback Quote is confirmed by test: mock `_get_quote` to return None, assert no fill row created
- [ ] Tests: network failure on open BUY order → no executed_actions row; retry on next cycle when quote available
