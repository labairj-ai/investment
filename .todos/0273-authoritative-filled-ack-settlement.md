# Require Authoritative Broker Fill Data Before Booking Filled ACK

- **ID:** 0273
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0271, 0269

## Problem

When `ack.normalized_state == "FILLED"`, `process_intent()` synthesizes a `BrokerFill` using `intent.limit_price` (or mid-quote) and hardcodes `fee=0.0`. This fabricates economic data: if the broker filled at a different price or charged a fee, cash, cost basis, and P&L are wrong from the moment the fill is recorded. When the broker later reports its authoritative fill under a different `broker_fill_id`, the importer may trigger `OverfillError` because the order is already locally marked fully filled. Additionally, when a `BrokerOrderEvent` is converted into a `BrokerFill` in both the submission-event path and the open-order path, `client_order_id` is not copied from the event, defeating the three-tier resolver for events where only `client_order_id` is known.

## Proposed approach

- Remove the synthetic fill path from `process_intent()` entirely.
- A FILLED ACK should: store `broker_order_id`, set `state='WORKING'`, then immediately call `broker.get_fills_for_order(broker_order_id)` to retrieve authoritative fill data. Call `apply_broker_fill()` for each returned fill.
- If `get_fills_for_order()` returns no fills or raises, leave the order as WORKING and let reconciliation ingest fills on the next cycle. Do not invent price, quantity, fee, timestamp, or fill ID.
- Add `get_fills_for_order(broker_order_id: str) -> list[BrokerFill]` to the `BrokerAdapter` ABC; implement in `ShadowBrokerAdapter` (query fills table) and `FakeBrokerAdapter` (return stored fills if any).
- When converting `BrokerOrderEvent` → `BrokerFill`, copy `client_order_id=event.client_order_id` in both the submission-event path and the open-order path in `execution_engine.py`.

## Touches

- `trade_engine/execution_engine.py` — remove synthetic fill; add get_fills_for_order call
- `trade_engine/broker_adapter.py` — `get_fills_for_order()` ABC method + ShadowBrokerAdapter impl
- `tests/fake_broker.py` — `get_fills_for_order()` impl
- `tests/test_chaos.py` — FILLED ACK test must now assert broker-authoritative price, not limit_price

## Done when

- [x] Synthetic fill path removed from `process_intent()`; no fill is invented from ACK data alone
- [x] `BrokerAdapter` ABC defines `get_fills_for_order(broker_order_id: str) -> list[BrokerFill]`
- [x] FILLED ACK stores broker_order_id, stays WORKING, calls `get_fills_for_order()`, applies real fills
- [x] If `get_fills_for_order()` returns empty or raises, order stays WORKING for reconciliation
- [x] `client_order_id` propagated from `BrokerOrderEvent` into created `BrokerFill` in all code paths
- [x] Existing chaos tests still pass; FILLED ACK test verifies broker-authoritative price used

## Outcome

Synthetic fill path removed from `process_intent()`. FILLED ACK now stores broker_order_id, keeps state=WORKING, calls `broker.get_fills_for_order(ack.broker_order_id)`, and applies each returned fill via `apply_broker_fill()`. If no fills returned, order stays WORKING for reconciliation to ingest later. `get_fills_for_order()` added to ABC; ShadowBrokerAdapter queries the fills table; FakeBrokerAdapter returns from `_broker_fills` dict (pre-staged on FILLED ACK submissions). `client_order_id` now propagated from `BrokerOrderEvent` into constructed `BrokerFill` in both `process_intent()` and `process_open_orders()` event paths.
