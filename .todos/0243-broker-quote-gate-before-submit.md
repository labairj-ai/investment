# Gate Broker Submission Behind Quote Freshness Check

- **ID:** 0243
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0238

## Problem

`process_intent()` and `process_open_orders()` call `_get_executable_quote()` directly from `market_data`, bypassing the broker abstraction — 0238 called for `broker.get_quote()` but that routing was reverted. More critically, `broker.submit_order(intent)` fires before any market-data freshness check. With `ShadowBroker` this is harmless; with a live adapter it means sending a real order before confirming broker-grade quote freshness, spread sanity, and price validity.

The correct pre-submit gate is: `broker.get_quote()` → freshness/spread/sanity check → *then* `broker.submit_order()`.

## Proposed approach

1. Remove `_get_executable_quote()` from `execution_engine.py` orchestration paths.
2. In `process_intent()`: call `broker.get_quote(symbol)` first; validate freshness, bid > 0, ask > 0, bid <= ask, spread within policy; *then* `broker.submit_order(intent)`. If quote missing or stale, return without submitting.
3. In `process_open_orders()`: use `broker.get_quote()` for retry-cycle freshness checks.
4. `_get_executable_quote` may remain in `market_data.py` for mark-price refresh (`_refresh_market_prices`) only.
5. Update test patches from `execution_engine._get_executable_quote` to `broker.get_quote` or `market_data._get_executable_quote`.

## Touches

- `trade_engine/execution_engine.py`
- `trade_engine/broker_adapter.py`
- `tests/test_trade_engine.py`
- `tests/test_broker_contract.py`

## Done when

- [ ] `process_intent()` calls `broker.get_quote()` before `broker.submit_order()`
- [ ] No order is submitted when quote is None or stale
- [ ] `process_open_orders()` uses `broker.get_quote()` for freshness checks
- [ ] `_get_executable_quote` is not called in execution orchestration paths
- [ ] All existing tests pass (mock patches updated as needed)
