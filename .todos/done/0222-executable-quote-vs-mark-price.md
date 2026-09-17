# Separate ExecutableQuote from MarkPrice; Enforce Quote Freshness Before Fill

- **ID:** 0222
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

Two related bugs. First: `_get_quote()` manufactures `bid = ask = last_price` when real bid/ask are unavailable, producing a zero-spread phantom quote that drives fill decisions — acceptable for position marking but not for execution simulation. Second: `attempt_fill()` validates bid/ask sanity but never checks `quote.retrieved_at` age, so an arbitrarily old quote can trigger a fill.

## Proposed approach

1. Split `_get_quote` into two functions (to live in `trade_engine/market_data.py` per todo 0225):
   - `_get_executable_quote(symbol) -> Optional[Quote]`: requires genuine `bid > 0` AND `ask > 0`; returns None if either is missing. Used in `process_intent()` and `process_open_orders()`.
   - `_get_mark_price(symbol) -> Optional[float]`: allows last-price fallback; used only in `_refresh_market_prices()` for position marking (never for fills).
2. In `attempt_fill()`: check `quote.retrieved_at` age vs `policy.halt_on_data_stale_minutes()`; if too old, return None and leave order WORKING.
3. Risk rule 15 (DATA_FRESHNESS): remove the equity skip; check equity quote `price_as_of` age vs policy threshold.

## Touches

- `trade_engine/execution_engine.py` — `_get_quote()` split, `process_intent()`, `_refresh_market_prices()`
- `trade_engine/market_data.py` (new, per 0225) — houses the two functions
- `trade_engine/shadow_broker.py` — `attempt_fill()` quote age check
- `trade_engine/risk_engine.py` — rule 15 equity skip removal
- `tests/test_trade_engine.py` — executable-quote and mark-price tests

## Done when

- [ ] `_get_executable_quote()` returns None when bid=0 or ask=0
- [ ] `_get_mark_price()` allows last-price fallback for position marking
- [ ] `process_intent()` and `process_open_orders()` use `_get_executable_quote()`
- [ ] `_refresh_market_prices()` uses `_get_mark_price()`
- [ ] `attempt_fill()` rejects quote older than policy staleness threshold
- [ ] Risk rule 15 enforces equity quote freshness (no equity skip)
- [ ] All existing tests pass
