# Fail Closed on Terminal-State Lookup Failure in poll_order_events

- **ID:** 0305
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0301

## Problem

When `poll_order_events()` detects that a tracked order has disappeared from the broker's open-orders list, it calls `get_order(broker_order_id)` to confirm the terminal state. If that lookup raises `BrokerSettlementIndeterminate`, the adapter currently catches the exception, adds the order back to `still_open`, and lets the cycle continue. The broker has confirmed the order is no longer open, but we cannot determine whether it filled, cancelled, expired, or was rejected — an unresolved known-unknown state. New order submissions must not proceed in this condition.

## Proposed approach

- In the per-order refresh loop inside `poll_order_events()`, remove the `except BrokerSettlementIndeterminate` clause that currently catches the `get_order()` error and retains the order in `still_open`. Let the exception propagate out of `poll_order_events()` to the caller.
- Update (or replace) the unit test that currently asserts `get_order()` errors are silently retained with one that asserts `BrokerSettlementIndeterminate` is raised.

## Touches

- `trade_engine/alpaca_adapter.py` — per-order refresh loop in `poll_order_events()`
- `tests/test_alpaca_adapter.py` — test covering `get_order()` failure after order leaves open set

## Done when

- [x] `get_order()` failure for an order absent from the open-orders list propagates as `BrokerSettlementIndeterminate` rather than retaining the order in `still_open`
- [x] Unit test asserts the exception is raised (not silently swallowed)
- [x] All existing tests pass

## Outcome

Removed the `try/except BrokerSettlementIndeterminate` around `get_order()` in the per-order
refresh loop. The exception now propagates to the caller. Added
`test_get_order_failure_after_order_leaves_open_set_propagates`. 705 tests pass.
