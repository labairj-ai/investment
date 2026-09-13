# Add Central Broker Identity Resolver

- **ID:** 0263
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** none

## Problem

The engine identifies orders using `order_id = event.local_order_id or event.broker_order_id` and then queries `WHERE order_id = ?` against the local primary key. This works only because ShadowBroker sets both IDs to the same value. For a real broker, local order ID (e.g. `"7a0d..."`) and broker order ID (e.g. `"295838472"`) differ, causing two concrete bugs: (1) `apply_broker_fill()` raises `UnknownFillError` for an event that supplies only `broker_order_id`, even though a local row with `broker_order_id='295838472'` exists. (2) `process_open_orders()` indexes events by `event.local_order_id or event.broker_order_id` but later fetches with `events_by_order.get(order.order_id, [])` — an event containing only a broker ID is silently dropped because it was stored under the wrong key.

## Proposed approach

- Introduce `resolve_local_order(local_order_id, broker_order_id, client_order_id, conn) -> Optional[str]` that tries in order:
  1. `orders.order_id = local_order_id` (exact PK match)
  2. `orders.broker_order_id = broker_order_id`
  3. `orders.client_order_id = client_order_id`
  4. Return `None` → caller raises `UnknownFillError` / halts
- Replace every ad-hoc `event.local_order_id or event.broker_order_id` pattern in `apply_broker_fill()`, `apply_broker_order_event()`, `process_open_orders()` event indexing, and reconciliation with a call to this resolver.
- In `process_open_orders()`, build the events map using the resolver key that matches `order.order_id`; alternatively, build a reverse map from broker_order_id → local order_id before the loop.
- Add an integration contract test with deliberately different IDs:
  - Local `order_id = "LOCAL-123"`, `broker_order_id = "BROKER-987"`, `client_order_id = "ACCOUNT:intent-abc"`
  - Broker event supplies only `broker_order_id="BROKER-987"`, `local_order_id=None`
  - Expected: event resolves to `LOCAL-123`, fill applied to `LOCAL-123`, cash/position updated exactly once.

## Touches

- `trade_engine/execution_engine.py` — `apply_broker_fill()`, `apply_broker_order_event()`, `process_open_orders()` event indexing
- `trade_engine/reconciliation.py` — broker→local lookup pass
- `tests/test_trade_engine.py` — new contract test with mismatched IDs
- `tests/test_chaos.py` — update any chaos tests that assume ID equality

## Done when

- [ ] `resolve_local_order(local_order_id, broker_order_id, client_order_id, conn)` exists and is the single resolution point used by all fill/event/reconciliation paths
- [ ] `apply_broker_fill()` resolves local order via all three ID fields; does not raise `UnknownFillError` when only `broker_order_id` matches a local row
- [ ] `process_open_orders()` event map keys resolve correctly when event carries only `broker_order_id`
- [ ] Integration contract test: `broker_order_id`-only event on an order with a different `local order_id` → fill applied exactly once, correct local order updated
- [ ] Shadow tests continue to pass (shadow case where all three IDs are identical is trivially covered by the resolver)
- [ ] 536+ existing tests continue to pass
