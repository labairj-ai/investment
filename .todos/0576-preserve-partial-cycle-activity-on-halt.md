# Preserve Partial Cycle Activity on Later HALT

- **ID:** 0576
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0575

## Problem

After `sync_broker_state()` succeeds and applies fills, any later HALTED return in the same cycle (e.g. `BrokerSubmissionIndeterminate` from `process_new_intents` or `BrokerStateIntegrityError` from `process_open_orders`) currently rebuilds from `_HALTED_BASE`. This discards already-earned counters: `broker_fills_observed`, `broker_fills_new`, `_seen_ids`, `_new_ids`, `fills_on_sync`, `total_fills`. A real fill can therefore occur during a cycle, a later stage halts, and `cycle_runs.fills_applied` is recorded as zero — an audit problem even though settlement is correct.

## Proposed approach

- After broker sync completes successfully, capture its fill counters and ID sets in a local variable before entering the intent/order-processing stages.
- Every HALTED return path that follows sync should merge those already-earned counters into the halted result rather than returning a fresh `_HALTED_BASE`.
- Open question: is there a single exit point that can be patched, or do each of the later halt branches need individual updates?

## Touches

- The runner/cycle orchestration module that calls `sync_broker_state()`, `process_new_intents()`, and `process_open_orders()` and builds the cycle result (exact path unknown — likely `runner.py` or `cycle.py`).
- Tests: add two new cases to the fill telemetry / cycle test suite.

## Done when

- [x] `sync applies fill → process_new_intents halts` → cycle result still reports the fill (broker_fills_new ≥ 1, fill ID present in _new_ids)
- [x] `sync applies fill → process_open_orders halts` → cycle result still reports the fill
- [x] No existing passing tests regress
- [x] `pytest` on main remains green

## Outcome

In `trade_engine/execution_engine.py` `run_execution_cycle()`: after `sync_broker_state()` succeeds, a `_sync_earned` dict captures `fills_on_sync`, `duplicate_fills_skipped`, `total_fills`, `broker_fills_*`, and `_seen_ids`/`_new_ids`. All four subsequent HALT returns (`BrokerSubmissionIndeterminate`, `BrokerStateIntegrityError` from intents, `PolicyUnavailable`, `BrokerStateIntegrityError` from open orders) now use `{**_HALTED_BASE, **_sync_earned, ...}` instead of bare `_HALTED_BASE`.

Added 4 parametrized tests in `tests/test_fill_hardening.py` covering all exception paths for both process stages. Full suite: 1449 passed, 0 failed.
