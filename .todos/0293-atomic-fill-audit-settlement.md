# Make Fill and Audit Settlement Atomic in One Transaction

- **ID:** 0293
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0289

## Problem

`apply_broker_fill()` commits the fill, order state, position, cash, and intent status atomically, but `executed_actions` is written afterward by individual callers via a separate `_write_executed_action()` call outside that transaction. A crash between the fill commit and the audit write leaves the economic ledger correct while the `executed_actions` row is permanently missing; on replay `apply_broker_fill()` returns `ALREADY_APPLIED` and callers that only write the audit on `APPLIED` silently skip it. Additionally, a broker order filled in multiple legs (e.g. 25 @ $50.00, 35 @ $49.98, 40 @ $49.95) can correctly update cash and positions for every partial fill but produce only a subset of `executed_actions` rows if callers process fills serially and short-circuit early.

## Proposed approach

- Move the `INSERT INTO executed_actions` inside `apply_broker_fill()`'s existing SQLite transaction, immediately before `COMMIT`, using the intent and fill data already in scope. The fill record and its audit record are then always committed together or not at all.
- Remove all `_write_executed_action()` call sites from callers (`sync_broker_state()`, `process_open_orders()`, and any other sites that currently call it after `apply_broker_fill()`).
- `_write_executed_action()` itself can be kept as a private helper called only from inside `apply_broker_fill()`, or inlined.
- Ensure the intent row (needed for `executed_actions`) is fetched inside the transaction before commit, not after. `apply_broker_fill()` already has access to `intent_id` via the order row.

## Touches

- `trade_engine/execution_engine.py` — `apply_broker_fill()`, `_write_executed_action()`, `sync_broker_state()`, `process_open_orders()`
- `tests/test_trade_engine.py` — new atomicity tests
- `tests/test_chaos.py` — verify replay leaves audit count unchanged

## Done when

- [x] `apply_broker_fill()` writes the `executed_actions` row inside its existing transaction before `COMMIT`
- [x] No caller calls `_write_executed_action()` after `apply_broker_fill()` returns
- [x] A three-part partial fill (three separate `BrokerFill` objects for one order) produces exactly three `fills` rows and exactly three `executed_actions` rows
- [x] Duplicate replay (`apply_broker_fill()` called twice with the same `broker_fill_id`) leaves both `fills` and `executed_actions` counts unchanged (idempotent)
- [x] All existing tests pass

## Outcome

Moved `executed_actions` INSERT inside `apply_broker_fill()` before `conn.commit()` for the APPLIED path. Added audit repair in the ALREADY_APPLIED path (idempotent — covers pre-0293 fills and shadow-mode fills inserted by ShadowBroker.attempt_fill()). Removed all `_write_executed_action()` call sites from process_intent(), process_open_orders(), and sync_broker_state(). `_write_executed_action()` definition kept as dead code (can be removed later). Added `TestAtomicFillAuditSettlement` in test_chaos.py with 4 tests.
