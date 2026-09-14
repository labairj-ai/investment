# Make poll_order_events Fail Closed on Broker Unreachability

- **ID:** 0301
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0299

## Problem

`poll_order_events()` has two paths that silently convert broker unreachability into "no events," undermining the authoritative pre-cycle broker sync. First, if `get_open_orders()` fails during the restart seed, the `except BrokerSettlementIndeterminate` block swallows the error and sets `_poll_seeded = True` anyway — the adapter never retries the seed and proceeds with an empty tracking set, missing any orders that were open at the broker. Second, if `get_open_orders()` fails during normal lifecycle polling, the method returns `[]` — the unit test explicitly asserts this behavior — so `sync_broker_state()` receives an empty event list and proceeds normally when it should halt.

## Proposed approach

- **Seed failure**: remove the bare `except` in the seed block; let `BrokerSettlementIndeterminate` propagate. Leave `_poll_seeded = False` so the next cycle retries the seed. The engine's HALTED path handles this correctly.
- **Normal poll failure**: remove the `except BrokerSettlementIndeterminate: return []` guard around `get_open_orders()`. Let the exception propagate so `sync_broker_state()` treats it as a broker-state failure and halts the cycle.
- Update the unit test `test_connectivity_error_keeps_order_tracked` to assert that the error is re-raised rather than returning an empty list.

## Touches

- `trade_engine/alpaca_adapter.py` — `poll_order_events()` seed block and normal-poll failure path
- `tests/test_alpaca_adapter.py` — update `TestPollOrderEvents::test_connectivity_error_keeps_order_tracked`

## Done when

- [x] A `BrokerSettlementIndeterminate` from `get_open_orders()` during the seed leaves `_poll_seeded = False` and propagates the exception
- [x] A `BrokerSettlementIndeterminate` from `get_open_orders()` during normal polling propagates rather than returning `[]`
- [x] Unit test verifies that connectivity failure raises, not returns empty
- [x] All existing tests pass

## Outcome

Removed try/except blocks from both seed and normal-poll paths. Seed failure now propagates
and leaves `_poll_seeded=False` for retry. Normal poll failure propagates as
`BrokerSettlementIndeterminate`. Renamed `test_connectivity_error_keeps_order_tracked` to
`test_connectivity_error_raises_settlement_indeterminate` and added
`test_seed_failure_leaves_poll_unseeded`. 702 tests pass.
