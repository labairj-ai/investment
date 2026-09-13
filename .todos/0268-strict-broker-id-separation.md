# Enforce Strict Local/Broker ID Separation in Adapter Interface

- **ID:** 0268
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0263, 0267

## Problem

`process_open_orders()` passes the local SQLite `order_id` to `broker.get_order()` and `broker.cancel_order()`, which works only because `ShadowBroker` conflates local and broker IDs (they are the same UUID). For real adapters (Alpaca, IBKR), these are completely separate namespaces — the broker issues its own opaque order ID on acceptance. Any code path that passes a local `order_id` to an external adapter will silently fail to find or cancel the correct order.

## Proposed approach

- `process_open_orders()` must `SELECT order_id, broker_order_id` from the `orders` table. Use `order_id` (local PK) for all local state transitions; use `broker_order_id` for all outbound adapter calls (`get_order`, `cancel_order`, `poll_order_events`).
- The immediate-fill path in `process_intent()` currently calls `broker.get_order(local_order_id)` — change to `broker.get_order(ack.broker_order_id)` (the ack already carries the broker-native ID).
- The `cancel_order()` signature should be documented to accept the broker's native ID; `ShadowBrokerAdapter` already uses `order_id` as the broker ID, so no behaviour change there, but the intent must be explicit.
- Add a hostile chaos test in `tests/test_chaos.py` where the `FakeBrokerAdapter` is seeded with a `broker_order_id` that is intentionally a different UUID from the local `order_id`. Assert that fills, cancellations, and event routing all land on the correct local row and never silently no-op.

## Touches

- `trade_engine/execution_engine.py` — `process_open_orders()`, `process_intent()`
- `trade_engine/broker_adapter.py` — `cancel_order()` doc/signature
- `tests/test_chaos.py` — hostile ID-mismatch test
- `tests/fake_broker.py` — may need a mode to issue a distinct `broker_order_id`

## Done when

- [x] `process_open_orders()` selects and separately tracks `order_id` and `broker_order_id`; local DB writes always use `order_id`, adapter calls always use `broker_order_id`
- [x] `process_intent()` calls `broker.get_order(ack.broker_order_id)` instead of the local ID
- [x] A hostile test exercises the full cycle (submit → event → fill → cancel) with `local_order_id ≠ broker_order_id` and asserts correct routing throughout
- [x] 558 tests pass (was 541)

## Outcome

`process_open_orders()` now SELECTs `broker_order_id`; `broker_oid = row["broker_order_id"] or row["order_id"]` is used for all six external broker calls (get_order ×3, cancel_order ×1 + related get_order ×2). `ShadowBrokerAdapter.get_open_orders()` updated to return actual `broker_order_id` from DB column. `FakeBrokerAdapter` gained `distinct_broker_id` mode + `_broker_to_local` mapping + overridden `get_order()`/`cancel_order()`. Three chaos tests: submit attaches distinct ID, fill event routes via broker ID, cancel uses broker ID.
