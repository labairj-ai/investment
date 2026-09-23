# Fix orders_created Semantics and Add Timeout Integration Test

- **ID:** 0579
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0578

## Problem

`_progress.orders_created` is incremented just before `broker.submit_order()`, which is the right general location but is reached on both a fresh `INSERT OR IGNORE` and a crash-restart re-entry where the INSERT was a no-op. A re-entered non-terminal order would therefore cause the HALTED summary to report `new_orders_created=1` despite zero new rows being created.

Additionally, the current criterion-1 test (`test_pending_submit_timeout_visible_in_halted_summary`) mocks `process_intent()` itself and manually increments `orders_created`. This proves CycleProgress propagation but not the actual production sequence: INSERT → commit → submit_order() → TimeoutError → BrokerSubmissionIndeterminate → HALTED summary.

## Proposed approach

- In `process_intent()`, capture the cursor from the `INSERT OR IGNORE INTO orders` statement and gate the increment: `if _progress is not None and cursor.rowcount == 1: _progress.orders_created += 1`. One line changes; no logic elsewhere needs to move.
- Add (or replace) the timeout test with a real end-to-end version using the actual `process_intent()` code: seed a PENDING intent, use a `PaperLedger`-style broker whose `submit_order()` raises `TimeoutError`, and run `run_execution_cycle()`. Assert both `(a) orders.state == 'PENDING_SUBMIT'` in the DB and `(b) result['new_orders_created'] == 1`.

## Touches

- `trade_engine/execution_engine.py` — one-line fix at the `INSERT OR IGNORE` commit site in `process_intent()`
- `tests/test_fill_hardening.py` — augment or replace `test_pending_submit_timeout_visible_in_halted_summary`

## Done when

- [x] `cursor.rowcount` gates `orders_created` increment; crash-restart re-entry of a non-terminal order no longer increments the counter
- [x] New integration-style test: real `process_intent()` + broker that raises `TimeoutError` from `submit_order()` → DB row has `state='PENDING_SUBMIT'` and `result['new_orders_created'] == 1`
- [x] All existing tests continue to pass (1,457)
