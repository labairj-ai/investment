# Fail Closed When Cancel and Lookup Both Return 404

- **ID:** 0303
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0297

## Problem

`cancel_order()` synthesizes a `CANCELLED` state when both the DELETE and the subsequent GET return 404/None: `state = order.state if order else "CANCELLED"`. A 404 on both calls means the broker has no record of this order ID — that is not evidence of cancellation. The order could have the wrong `broker_order_id`, or there could be a mapping or state-history issue. Treating absence as `CANCELLED` could allow the engine to proceed as if an order is closed when its actual disposition is unknown.

## Proposed approach

- In `cancel_order()`, after the DELETE returns 404/422 (`accepted = False`) and the subsequent `get_order()` returns `None`, raise `BrokerSettlementIndeterminate` instead of constructing a synthetic `BrokerCancelAck(normalized_state="CANCELLED")`.
- Only construct a `BrokerCancelAck` when `get_order()` returns an actual broker state.
- Update the unit test `test_cancel_404_not_accepted` to assert that this case raises `BrokerSettlementIndeterminate` rather than returning a cancel ack.
- A 404 on the DELETE alone (order already closed) combined with a successful `get_order()` returning a real terminal state (e.g. FILLED, EXPIRED) should still return a valid ack — only the double-404 case should raise.

## Touches

- `trade_engine/alpaca_adapter.py` — `cancel_order()`
- `tests/test_alpaca_adapter.py` — `TestCancelOrder::test_cancel_404_not_accepted`

## Done when

- [x] `cancel_order()` raises `BrokerSettlementIndeterminate` when DELETE returns 404/422 and `get_order()` returns `None`
- [x] `cancel_order()` returns a valid `BrokerCancelAck` when DELETE returns 404 but `get_order()` returns a real terminal state
- [x] Unit test updated to assert the double-404 case raises rather than returning a synthetic ack
- [x] All existing tests pass

## Outcome

`cancel_order()` now raises `BrokerSettlementIndeterminate` when both DELETE and GET return
not-found. Renamed `test_cancel_404_not_accepted` to
`test_cancel_404_raises_when_get_also_404` and added
`test_cancel_404_but_get_returns_terminal_state` to cover the DELETE-404 + GET-EXPIRED path.
702 tests pass.
