# Separate Broker Execution Lifecycle From Shadow Fill Simulation

- **ID:** 0248
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0243, 0247

## Problem

`attempt_fill(order, quote)` is a synchronous shadow simulation concept that does not map to a real broker. A live adapter receives order acknowledgments, partial fills, and cancellation confirmations as asynchronous events — not as the return value of a single call. Defining `attempt_fill()` as an abstract method on `BrokerAdapter` forces every real adapter to bend asynchronous broker behavior into a synchronous shadow simulation shape, which will produce incorrect lifecycle semantics.

## Proposed approach

1. Remove `attempt_fill()` from `BrokerAdapter` ABC. It belongs only on `ShadowBroker` as a simulation helper.
2. Replace with a lifecycle-oriented interface:
   - `place_order(intent, quote) -> BrokerOrder` — submit and return broker acknowledgment
   - `request_cancel(broker_order_id) -> None` — fire cancel; confirmation arrives via events
   - `poll_order_events(account_id, since) -> list[BrokerOrderEvent]` — order state changes (fills, cancels, expirations)
3. `ShadowBrokerAdapter` implements `poll_order_events()` by simulating synchronous fill/expire behavior internally, making shadow mode still work end-to-end.
4. The execution engine drives the state machine from events rather than from `attempt_fill()` return values.
5. `BrokerOrderEvent` NamedTuple in `broker_types.py`: `event_type` (FILLED, PARTIALLY_FILLED, CANCELLED, EXPIRED), `broker_order_id`, `fill_qty`, `fill_price`, `filled_at`.

## Touches

- `trade_engine/broker_types.py` — new `BrokerOrderEvent`
- `trade_engine/broker_adapter.py` — remove `attempt_fill()`, add `place_order()`, `request_cancel()`, `poll_order_events()`
- `trade_engine/execution_engine.py` — drive fills from events
- `trade_engine/shadow_broker.py` — `attempt_fill()` stays as simulator; not exposed on adapter
- `tests/test_broker_contract.py` — update contract to new lifecycle methods

## Done when

- [ ] `attempt_fill()` is removed from `BrokerAdapter` ABC
- [ ] `BrokerAdapter` exposes `place_order()`, `request_cancel()`, `poll_order_events()`
- [ ] `ShadowBrokerAdapter.poll_order_events()` produces correct fill/expire events
- [ ] Execution engine drives order lifecycle from events, not from `attempt_fill()` return value
- [ ] Contract tests updated; all tests pass
