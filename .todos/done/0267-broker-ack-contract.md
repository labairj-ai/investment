# Change submit_order to Return BrokerOrderAck

- **ID:** 0267
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0263, 0264

## Problem

`BrokerAdapter.submit_order()` currently returns the local `Order` model. This works for `ShadowBrokerAdapter` because it writes directly to the local SQLite database, but it is architecturally wrong for real broker adapters, which should not touch the local ledger at all. A real adapter should translate the broker's HTTP response into a normalized acknowledgement and return it; the execution engine then owns attaching `broker_order_id` to the local `PENDING_SUBMIT` row. The current design couples the adapter to local DB schema, making it impossible to write a clean Alpaca or IBKR adapter without also granting it database write access.

## Proposed approach

- Add `BrokerOrderAck(NamedTuple)` to `broker_types.py`:
  ```python
  class BrokerOrderAck(NamedTuple):
      broker_order_id: str
      client_order_id: Optional[str]
      normalized_state: str        # "WORKING", "PENDING", etc.
      accepted_at: str             # ISO timestamp from broker
      raw_status: Optional[str]    # broker-native status string for debugging
  ```
- Change `BrokerAdapter.submit_order()` ABC to return `BrokerOrderAck`.
- Update `ShadowBrokerAdapter.submit_order()` to continue writing to the local DB internally (backward-compatible for shadow mode) but return a `BrokerOrderAck` constructed from the created order.
- Update `FakeBrokerAdapter.submit_order()` accordingly; its `_broker_orders` dict already models this correctly.
- Update `process_intent()` to consume `BrokerOrderAck`:
  ```python
  ack = broker.submit_order(intent, client_order_id=client_order_id)
  conn.execute(
      "UPDATE orders SET broker_order_id=?, state='WORKING', submitted_at=? WHERE order_id=?",
      (ack.broker_order_id, ack.accepted_at, pending_order_id)
  )
  ```
- All callers that currently use the returned `Order` object's `order_id` for subsequent lookups should switch to `ack.broker_order_id` (or resolve via the identity resolver from 0263).

## Touches

- `trade_engine/broker_types.py` — `BrokerOrderAck` type
- `trade_engine/broker_adapter.py` — `BrokerAdapter.submit_order()` ABC and `ShadowBrokerAdapter.submit_order()`
- `trade_engine/execution_engine.py` — `process_intent()` consumes `BrokerOrderAck`
- `tests/fake_broker.py` — `FakeBrokerAdapter.submit_order()` return type
- `tests/test_trade_engine.py` — update submit_order mock return values and assertions

## Done when

- [ ] `BrokerOrderAck` named tuple exists in `broker_types.py` with `broker_order_id`, `client_order_id`, `normalized_state`, `accepted_at`, `raw_status`
- [ ] `BrokerAdapter.submit_order()` ABC declares return type `BrokerOrderAck`
- [ ] `ShadowBrokerAdapter.submit_order()` returns `BrokerOrderAck`; shadow DB writes still occur internally
- [ ] `process_intent()` uses `BrokerOrderAck.broker_order_id` to UPDATE the local `PENDING_SUBMIT` row; does not rely on the adapter having mutated the local row
- [ ] `FakeBrokerAdapter.submit_order()` returns `BrokerOrderAck`
- [ ] No adapter implementation directly writes to `orders` table except `ShadowBrokerAdapter` (which is a special-case shadow-mode adapter)
- [ ] 536+ existing tests continue to pass
