# Halt Account on Indeterminate Broker Submission

- **ID:** 0265
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0264

## Problem

When `broker.submit_order()` raises a network-class exception (e.g. `TimeoutError`) after `PENDING_SUBMIT` has been written to the local DB, the broker's acceptance of that order is unknown. `process_new_intents()` currently catches all exceptions, logs them, and continues processing subsequent intents. `run_execution_cycle()` can therefore return `execution_state="OK"` even though the account has an order whose existence at the broker is uncertain. For a real broker this is unsafe: submitting a second intent while the first is in unknown state may create a duplicate position or cause the unknown order to be excluded from risk calculations.

## Proposed approach

- Introduce `BrokerSubmissionIndeterminate(RuntimeError)` raised by `process_intent()` when `submit_order()` throws any network-class or timeout exception after `PENDING_SUBMIT` is durably written.
- `process_new_intents()` must not swallow `BrokerSubmissionIndeterminate`. When it is raised, stop processing further intents and propagate an account-halted signal.
- `run_execution_cycle()` must return `execution_state="HALTED"`, `halt_reason="SUBMISSION_INDETERMINATE"` when any intent triggers this exception.
- The designated recovery path is reconciliation by `client_order_id`: either the broker has the order (attach ACK, advance local row to WORKING) or definitively does not (safe to cancel `PENDING_SUBMIT` and optionally retry). This is already the reconciliation model from 0260/0264.
- Add `FakeBrokerAdapter` mode for post-PENDING_SUBMIT timeout to simulate this scenario cleanly (distinct from `submit_timeout` which writes to `_broker_orders` before raising; this mode should raise without writing so broker definitively does not have the order, covering the other branch).
- Tests:
  - Two PENDING intents; intent #1 causes `BrokerSubmissionIndeterminate`; assert intent #2 is never submitted.
  - `run_execution_cycle()` returns `execution_state="HALTED"` with `halt_reason="SUBMISSION_INDETERMINATE"`.
  - After successful reconciliation (broker confirms order), `initialize_trading_session()` returns `TRADING_READY` and a subsequent cycle can process intent #2.

## Touches

- `trade_engine/execution_engine.py` — `process_intent()` (raise `BrokerSubmissionIndeterminate`), `process_new_intents()` (stop on indeterminate), `run_execution_cycle()` (HALTED propagation)
- `trade_engine/models.py` — `BrokerSubmissionIndeterminate` exception class
- `tests/fake_broker.py` — new chaos mode for post-PENDING_SUBMIT timeout without broker-side write
- `tests/test_chaos.py` — multi-intent circuit-breaker test
- `tests/test_trade_engine.py` — unit test for HALTED cycle result

## Done when

- [ ] `BrokerSubmissionIndeterminate` exception class exists and is raised by `process_intent()` when submission network error occurs after `PENDING_SUBMIT` is written
- [ ] `process_new_intents()` does not swallow `BrokerSubmissionIndeterminate`; stops processing further intents for the account when it is raised
- [ ] `run_execution_cycle()` returns `execution_state="HALTED"`, `halt_reason="SUBMISSION_INDETERMINATE"` when any intent raises `BrokerSubmissionIndeterminate`
- [ ] Test: two pending intents, intent #1 raises `BrokerSubmissionIndeterminate`, intent #2 is never submitted (`broker.submit_order.call_count == 1`)
- [ ] Test: after recovery reconciliation, next cycle can process intent #2 successfully
- [ ] 536+ existing tests continue to pass
