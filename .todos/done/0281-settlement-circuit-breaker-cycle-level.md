# Catch BrokerSettlementIndeterminate at run_execution_cycle Level

- **ID:** 0281
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0278

## Problem

`process_new_intents()` correctly re-raises `BrokerSettlementIndeterminate`, but `run_execution_cycle()` only catches `BrokerSubmissionIndeterminate` (returning `HALTED / halt_reason="SUBMISSION_INDETERMINATE"`). When a FILLED ACK triggers `BrokerSettlementIndeterminate`, it propagates through `process_new_intents` → `run_execution_cycle` uncaught, escaping the cycle entirely as an unhandled exception rather than a controlled trading halt. Depending on the service wrapper this surfaces as an exception or 500 rather than an auditable `HALTED` state. Additionally, `get_fills_for_order()` in `broker_adapter.py` still carries a docstring saying an empty return means the order stays WORKING until reconciliation — that is no longer true after 0278, where an empty return after a FILLED ACK raises `BrokerSettlementIndeterminate`. The stale docstring must be corrected before a real adapter is written.

## Proposed approach

- In `run_execution_cycle()`: add `except BrokerSettlementIndeterminate` alongside the existing `except BrokerSubmissionIndeterminate`, returning `HALTED` with `halt_reason="SETTLEMENT_INDETERMINATE"` (or the cycle's equivalent controlled-halt return value).
- Update the `get_fills_for_order()` abstract method docstring in `broker_adapter.py` to accurately describe the post-0278 contract: an empty list after a FILLED ACK raises `BrokerSettlementIndeterminate`; an empty list during reconciliation or PARTIALLY_FILLED recovery is silently tolerated.
- Test: trigger `BrokerSettlementIndeterminate` via `run_execution_cycle()` (not just `process_new_intents()`); assert the return value signals HALTED rather than raising.

## Touches

- `trade_engine/execution_engine.py` — `run_execution_cycle()` exception handler
- `trade_engine/broker_adapter.py` — `get_fills_for_order()` docstring
- `tests/test_chaos.py` or `tests/test_trade_engine.py` — cycle-level settlement-indeterminate test

## Done when

- [x] `run_execution_cycle()` catches `BrokerSettlementIndeterminate` and returns a controlled HALTED state (not an unhandled exception)
- [x] Return value matches the existing `BrokerSubmissionIndeterminate` halt pattern (same halt_reason field or equivalent)
- [x] `get_fills_for_order()` docstring in `broker_adapter.py` accurately describes post-0278 semantics
- [x] Test drives `BrokerSettlementIndeterminate` through the full `run_execution_cycle()` call path and asserts HALTED (not an exception)
- [x] All existing 580 tests still pass (589 pass total with new tests)

## Outcome

Added `except BrokerSettlementIndeterminate` alongside the existing `BrokerSubmissionIndeterminate` handler in `run_execution_cycle()` for both the `process_new_intents` and `process_open_orders` call sites — both return `{**_HALTED_BASE, "halt_reason": "SETTLEMENT_INDETERMINATE"}`. Updated `get_fills_for_order()` docstring in `broker_adapter.py` to accurately describe post-0278/0282 semantics (three distinct contexts with different empty-return handling). Added `TestSettlementIndeterminateCycleLevel` with 2 tests: one verifying HALTED state, one verifying no unhandled exception escapes.
