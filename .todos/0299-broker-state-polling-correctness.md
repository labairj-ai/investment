# Fix poll_order_events to Refresh Open Orders by ID

- **ID:** 0299
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0297

## Problem

`AlpacaAdapter.poll_order_events()` polls `GET /v2/orders?status=all&after={last_poll_ts}` where Alpaca's `after` parameter filters by order *submission* time, not by last state-change time. Any order submitted before the watermark that later fills, cancels, or is rejected will be excluded from the response — those events are silently dropped. The durable `get_fills()` ledger pull rescues fill economics, but cancellation and rejection events can be permanently missed, leaving local orders stuck in WORKING state indefinitely.

## Proposed approach

- Remove the `_last_poll_ts` watermark and the `after` parameter from `poll_order_events()` entirely.
- Replace with explicit per-order refresh: for each order currently in a locally open state (WORKING, PARTIALLY_FILLED), call `get_order(broker_order_id)` and emit a `BrokerOrderEvent` if the broker-reported state differs from the locally known state.
- Keep the durable `GET /v2/account/activities/FILL` pull (`get_fills()`) as the canonical fill source — it already runs every cycle via `sync_broker_state()`.
- Add a comment noting that Alpaca's trade-update stream (WebSocket/SSE) is the preferred long-term replacement for this polling approach; the per-order refresh is intentionally simple and deterministic for a low-frequency system.
- Open question: should `poll_order_events()` receive the list of locally open broker order IDs as a parameter, or should the adapter query the local DB directly? Keeping DB access out of the adapter is cleaner — pass the IDs from the engine layer.

## Touches

- `trade_engine/alpaca_adapter.py` — `poll_order_events()`, remove `_last_poll_ts`
- `tests/test_alpaca_adapter.py` — update `TestPollOrderEvents` to reflect per-order refresh behavior

## Done when

- [ ] `poll_order_events()` no longer uses a submitted-at watermark or `after` parameter
- [ ] `poll_order_events()` refreshes each locally open order via `get_order(broker_order_id)` and emits events for state changes
- [ ] An order submitted before the previous poll cycle that fills or cancels produces a `BrokerOrderEvent` (regression test with mocked HTTP)
- [ ] `_last_poll_ts` instance variable removed from `AlpacaAdapter`
- [ ] All existing tests pass
