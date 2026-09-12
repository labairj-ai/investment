# Quote Freshness Must Be Source-Aware (Shadow vs Paper/Live)

- **ID:** 0235
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0237

## Problem

`_is_quote_fresh()` (`execution_engine.py:93`) allows `market_timestamp=None, retrieved_at=now` → FRESH. The tests explicitly preserve this as backward compatibility for the yfinance/shadow path. That's acceptable for shadow-only operation.

For a paper or live broker adapter, this is too loose: the broker returns quotes with authoritative exchange timestamps, and missing `market_timestamp` from a broker is a data quality failure — not a fallback to allow. Executing on a broker quote with no market observation time is not safe.

## Proposed approach

Add a `require_market_timestamp: bool = False` parameter to `_is_quote_fresh()`:

```python
def _is_quote_fresh(quote: Quote, stale_minutes: int, *, require_market_timestamp: bool = False) -> bool:
    if require_market_timestamp and not quote.market_timestamp:
        return False  # broker quotes must have exchange observation time
    ...  # existing logic unchanged
```

All current callers pass `require_market_timestamp=False` (default), so shadow behavior is unchanged.

When B1 paper adapter is built, calls that originate from a `BrokerAdapter` with `source != "shadow"` pass `require_market_timestamp=True`. Wire this through `process_open_orders()` and `process_intent()` — both already have access to the broker/quote source — or alternatively expose it as a property on `BrokerAdapter`: `adapter.requires_market_timestamp: bool`.

Add tests:
- Shadow quote with no `market_timestamp`, fresh `retrieved_at` → FRESH (backward compat)
- Broker quote with no `market_timestamp`, fresh `retrieved_at`, `require_market_timestamp=True` → STALE (fail closed)
- Broker quote with fresh `market_timestamp` and `retrieved_at` → FRESH

## Touches

- `trade_engine/execution_engine.py` — `_is_quote_fresh()` signature and body
- `trade_engine/broker_adapter.py` — add `requires_market_timestamp` property to `BrokerAdapter` protocol (optional, for wiring)
- `tests/test_trade_engine.py` — new tests in `TestQuoteFreshnessMarketTimestamp`

## Done when

- [ ] `_is_quote_fresh(..., require_market_timestamp=True)` returns `False` when `market_timestamp` is absent
- [ ] Default behavior (`require_market_timestamp=False`) is unchanged — all 172 existing tests pass
- [ ] Three new tests: shadow fallback, broker-strict miss, broker-strict pass
