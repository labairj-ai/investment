# Enforce Quote Freshness: market_timestamp, Staleness Gate Before Fill

- **ID:** 0213
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`Quote` (shadow_broker.py:22) is `NamedTuple(bid, ask, timestamp)` where `timestamp = _now_utc().isoformat()` — the retrieval time, not the time of the underlying market observation. A yfinance `last_price` could be hours old (after-hours, stale feed) but is timestamped as "just now." `attempt_fill()` never checks staleness, never validates `bid > 0`, `ask > 0`, or `bid <= ask`. This is cited in the B0 todo as a known gap; it matters more once a real paper-broker adapter is connected.

## Proposed approach

1. Evolve `Quote` (in `shadow_broker.py`) with backward-compatible optional fields:
   ```python
   class Quote(NamedTuple):
       bid: float
       ask: float
       timestamp: str                      # kept for compat (= retrieved_at)
       market_timestamp: Optional[str] = None   # when the exchange last traded
       retrieved_at: Optional[str] = None       # when we fetched from the feed
       source: str = "yfinance"
   ```

2. Update `_get_quote()` in `execution_engine.py` to populate `market_timestamp` from yfinance `info.regularMarketTime` (unix timestamp, convert to ISO). Set `retrieved_at = _now_utc().isoformat()`.

3. Add `_validate_quote(quote, policy)` helper in `shadow_broker.py`:
   - `quote.bid > 0` and `quote.ask > 0`
   - `quote.bid <= quote.ask`
   - If `retrieved_at` is set: age in minutes ≤ `policy.halt_on_data_stale_minutes()`
   Returns `True` if valid, `False` otherwise.

4. In `attempt_fill()`: call `_validate_quote(quote, policy)` — but `attempt_fill()` doesn't currently have access to `policy`. Options: (a) pass `policy` into `attempt_fill()`, or (b) pass `max_stale_minutes` directly. Prefer (a) for future extensibility.

5. Update `ShadowBroker.__init__` or `attempt_fill` signature accordingly.

## Touches

- `trade_engine/shadow_broker.py` — `Quote`, `attempt_fill()`, new `_validate_quote()`
- `trade_engine/execution_engine.py` — `_get_quote()` to populate `market_timestamp`
- `tests/test_trade_engine.py` — staleness tests, sanity check tests

## Done when

- [ ] `Quote` has `market_timestamp`, `retrieved_at`, `source` optional fields (backward compat: existing `Quote(bid, ask, timestamp)` still works)
- [ ] `_get_quote()` populates `market_timestamp` from yfinance when available
- [ ] Quote with `bid=0` → no fill
- [ ] Quote with `bid > ask` → no fill
- [ ] Quote with `retrieved_at` > `halt_on_data_stale_minutes` ago → no fill
- [ ] Fresh valid quote → fill proceeds normally
- [ ] All 391 existing tests still pass
