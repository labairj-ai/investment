# Migrate Execution Engine to Consume BrokerOrderEvent

- **ID:** 0256
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0248, 0252

## Problem

`BrokerOrderEvent` and `poll_order_events()` were introduced in 0248, but the execution
engine's `process_open_orders()` still drives fill decisions by calling
`broker.attempt_fill()` directly on each open order. The engine therefore remains
ShadowBroker-shaped: it only works correctly when the broker simulates fills
synchronously in response to a direct call. A real Alpaca or IBKR adapter would not
implement `attempt_fill()`; it would emit events asynchronously via `poll_order_events()`.
The bridge from the interface (0248) to the engine has not been built.

## Proposed approach

1. In `process_open_orders()`, replace the `broker.attempt_fill(order, quote)` call with
   `broker.poll_order_events(account_id, quote=bquote)`.
2. For each returned `BrokerOrderEvent`, dispatch on `event_type`:
   - `FILLED` / `PARTIALLY_FILLED` → construct a `BrokerFill` from the event fields and
     call `apply_broker_fill()` (0252) — this is the single write path for all fills.
   - `CANCELLED` → transition order to `CANCELLED`, write audit record.
   - `EXPIRED` → transition order to `EXPIRED`.
   - Unknown type → log a warning, leave the order unchanged (fail-safe, not fail-open).
3. `ShadowBrokerAdapter.poll_order_events()` already simulates synchronously — no
   ShadowBroker changes needed for test compatibility.
4. Remove or mark `attempt_fill()` as a shadow-internal helper; the abstract base class
   should no longer declare it (it was already demoted to non-abstract in 0248).
5. Update test patches: any test that calls `broker.attempt_fill()` directly and expects
   the engine to see the result must be updated to use `poll_order_events()` instead.
6. Contract test (`test_broker_contract.py`): assert that `poll_order_events()` is called
   once per `process_open_orders()` cycle and that `attempt_fill()` is not called.

## Touches

- `trade_engine/execution_engine.py` — `process_open_orders()`
- `trade_engine/broker_adapter.py` — remove `attempt_fill()` from ABC if not already done
- `tests/test_trade_engine.py` — update fill-path tests
- `tests/test_broker_contract.py` — new contract assertion

## Done when

- [x] `process_open_orders()` drives fills exclusively via `broker.poll_order_events()`
- [x] `attempt_fill()` is not called by the execution engine in any code path
- [x] `FILLED`, `PARTIALLY_FILLED`, `CANCELLED`, and `EXPIRED` events are each handled correctly
- [x] Unknown event type is logged and skipped without mutation
- [x] `ShadowBrokerAdapter` tests pass without changes to the shadow implementation
- [x] `broker_fill_id` field added to `BrokerOrderEvent` for deduplication; `ShadowBrokerAdapter.poll_order_events()` populates it
- [x] All existing tests pass (520 passed, 1 skipped)

## Outcome

`process_open_orders()` calls `broker.poll_order_events(account_id, quote=bquote)` once per cycle; filters events by `event.local_order_id == order.order_id`; dispatches FILLED/PARTIALLY_FILLED → `apply_broker_fill()` → `_write_executed_action`; CANCELLED/EXPIRED → pass; unknown → warning. `ShadowBrokerAdapter.poll_order_events()` maps quote by symbol for multi-symbol correctness and includes `broker_fill_id` for downstream deduplication.
