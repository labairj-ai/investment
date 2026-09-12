# Quote Freshness Must Use Market Observation Time, Not Retrieval Time

- **ID:** 0232
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`_is_quote_fresh()` (`execution_engine.py:89`) checks `retrieved_at` only. If `retrieved_at` is missing or unparseable, the function returns `True` — fail open. A quote retrieved at 1:30 PM that contains a market observation from 11:00 AM is considered fresh because the retrieval timestamp is recent.

`_refresh_market_prices()` (`execution_engine.py:118`) writes `price_as_of = _now_utc().isoformat()` — the time our code ran the refresh, not the time the market price was actually valid. For risk purposes, `price_as_of` should mean "when was this price observed in the market," not "when did we call yfinance."

## Proposed approach

- In `_is_quote_fresh()`: check `market_timestamp` first if present — its age must be ≤ `stale_minutes`. Then check `retrieved_at` as a secondary transport-freshness bound. If either timestamp is missing or unparseable, return `False` (fail closed). Remove the `return True` fallback paths.
- In `_refresh_market_prices()`: change `price_as_of` to `quote.market_timestamp or _now_utc().isoformat()`. If the quote carries a market observation time, record that; fall back to retrieval time only if no market timestamp is available.
- In `trade_engine/market_data.py` / `_get_mark_price()`: consider returning a small struct `{price: float, market_timestamp: str, retrieved_at: str, source: str}` instead of just `float`. This makes it possible to thread `market_timestamp` all the way to `price_as_of` without guessing. This is a bigger change — if deferred, leave a TODO comment and add a follow-up story.
- Tests: quote with `retrieved_at=now` but `market_timestamp` 3 hours ago → `_is_quote_fresh()` returns False. Quote with no `retrieved_at` and no `market_timestamp` → False. Quote with both timestamps fresh → True.

## Touches

- `trade_engine/execution_engine.py` — `_is_quote_fresh()`, `_refresh_market_prices()`
- `trade_engine/market_data.py` — consider struct return from `_get_mark_price()` (may be split into follow-up)
- `tests/test_trade_engine.py` — freshness tests for all three cases above

## Done when

- [ ] `_is_quote_fresh()` returns False when `market_timestamp` is stale, even if `retrieved_at` is recent
- [ ] `_is_quote_fresh()` returns False when either timestamp is missing or unparseable (no fail-open)
- [ ] `_refresh_market_prices()` writes `price_as_of = market_timestamp` when available
- [ ] Tests covering stale observation time, missing timestamps, and fresh timestamps all pass
