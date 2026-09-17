# Broker-State Integrity Circuit Breaker

- **ID:** 0288
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** none

## Problem

`BrokerFillInvalid` (added in 0286) is raised before any DB mutation when a fill fails identity or economics validation — but the callers don't consistently treat this as the account-halting safety event the validator intends. In `process_new_intents()`, only `BrokerSubmissionIndeterminate` and `BrokerSettlementIndeterminate` are explicitly re-raised; everything else falls into `except Exception`, gets logged, and processing continues to the next intent. A malformed fill from a mistranslating adapter (wrong symbol, wrong side) would therefore be logged and skipped rather than halting the account. The same gap applies at the `run_execution_cycle()` level: `BrokerFillInvalid`, `OverfillError`, `ImpossibleSellError`, and `UnknownFillError` are not part of the `BrokerSettlementIndeterminate` catch, so they bubble out as unhandled exceptions instead of producing a controlled `HALTED/BROKER_STATE_INTEGRITY` result.

## Proposed approach

- Introduce a common base exception `BrokerStateIntegrityError` in `execution_engine.py` (or `broker_types.py`).
- Make `BrokerFillInvalid`, `OverfillError`, `ImpossibleSellError`, `UnknownFillError`, and `BrokerSettlementIndeterminate` all subclass `BrokerStateIntegrityError`.
- In `process_new_intents()`: replace bare `except Exception` pass-through with an explicit `except BrokerStateIntegrityError: raise` before the generic handler, so integrity failures propagate.
- In `run_execution_cycle()`: catch `BrokerStateIntegrityError` (not just `BrokerSettlementIndeterminate`) at every call site that touches broker I/O — `sync_broker_state()`, `process_new_intents()`, `process_open_orders()` — and return `HALTED/halt_reason="BROKER_STATE_INTEGRITY"`.
- Add a cycle-level integration test: submit intent #1 → adapter returns a fill with wrong symbol → `BrokerFillInvalid` raised → cycle returns HALTED → intent #2 is never submitted.

## Touches

- `trade_engine/execution_engine.py` — exception hierarchy, `process_new_intents()`, `run_execution_cycle()`
- `trade_engine/broker_types.py` — possibly move base exception here
- `tests/test_chaos.py` — cycle-level test proving intent #2 is blocked on invalid fill

## Outcome

`BrokerStateIntegrityError(RuntimeError)` added before the existing exception classes. `UnknownFillError`, `OverfillError`, `ImpossibleSellError`, `BrokerFillInvalid`, and `BrokerSettlementIndeterminate` all changed to subclass it. `BrokerSubmissionIndeterminate` deliberately kept as standalone `RuntimeError` (network uncertainty ≠ fill integrity). `apply_broker_fill()` rollback handler simplified to `except BrokerStateIntegrityError`. `process_new_intents()` re-raise clause updated to `except (BrokerSubmissionIndeterminate, BrokerStateIntegrityError)`. All three `except BrokerSettlementIndeterminate` catches in `run_execution_cycle()` changed to `except BrokerStateIntegrityError` returning `halt_reason="BROKER_STATE_INTEGRITY"`. Four existing tests updated from `"SETTLEMENT_INDETERMINATE"` to `"BROKER_STATE_INTEGRITY"`. Two new tests in `TestBrokerStateIntegrityCircuit`: cycle-level halt on intent #1 leaves intent #2 PENDING; subclass hierarchy verified. Suite: 614 passed, 1 skipped. Next: 0289 (durable fill ledger), 0290 (REJECTED event), 0291 (Alpaca URL allowlist).

## Done when

- [x] `BrokerStateIntegrityError` base exception exists and all fill-integrity exceptions subclass it
- [x] `process_new_intents()` re-raises `BrokerStateIntegrityError` instead of logging-and-continuing
- [x] `run_execution_cycle()` catches `BrokerStateIntegrityError` at all broker-touching call sites and returns `HALTED/halt_reason="BROKER_STATE_INTEGRITY"`
- [x] Cycle-level test: invalid fill on intent #1 → HALTED, intent #2 not submitted
- [x] All existing 612 tests still pass (614 now, +2 new)
