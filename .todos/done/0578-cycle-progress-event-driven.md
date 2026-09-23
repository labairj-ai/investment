# Make CycleProgress Truly Event-Driven Across All Stages

- **ID:** 0578
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** none

## Problem

0577 introduced `CycleProgress` and made `process_open_orders()` update it in-flight, but two stages still have gaps where durable mutations can occur before an exception is raised without those facts reaching the progress object.

**1. Submission indeterminate (most important):** `process_intent()` writes a durable `PENDING_SUBMIT` order to the DB before calling `broker.submit_order()`. If submission times out and raises `BrokerSubmissionIndeterminate`, `process_new_intents()` never returns an `ExecutionResult`, so `progress.new_results` stays empty. The cycle summary reports `new_orders_created=0` even though a real local order exists. The same gap applies to partial immediate-fill paths inside `process_intent()`.

**2. Partial sync failure:** `sync_broker_state()` can successfully apply a fill early in its run, then encounter a `BrokerStateIntegrityError` on a later ledger item and raise. `progress.sync_fills` is only populated after `sync_broker_state()` returns successfully, so `fills_on_sync=0 / total_fills=0` despite a committed fill. The broker ID telemetry (`broker_fills_new`) survives via `_fill_stats`, but the fill counts are inconsistent.

**3. Duplicate retry counting (smaller, older bug):** `process_open_orders()` appends a fill to `progress.retry_fills` whenever `fill_row` exists after `apply_broker_fill()`, without checking whether the result was `APPLIED` or `ALREADY_APPLIED`. A replayed broker event can therefore inflate `fills_on_retry` and `total_fills` with no new economic mutation.

## Proposed approach

- Pass `_progress` into `process_new_intents()` / `process_intent()` the same way it is now passed into `process_open_orders()`. Update progress at the moment each durable fact is committed:
  - `PENDING_SUBMIT` row written → increment `progress.orders_created` (or update a new `orders_submitted_indeterminate` counter)
  - broker ACK received → record confirmed submission
  - authoritative fill `APPLIED` → append to `progress.submission_fills`
  - risk rejection committed → increment rejection count
- Pass `_progress` into `sync_broker_state()` and append newly `APPLIED` fills to `progress.sync_fills` as they occur, rather than bulk-assigning after a successful return. This also eliminates the `_merge_invocation_broker_stats()` asymmetry.
- In `process_open_orders()`, check the return value of `apply_broker_fill()`: only append to `retry_fills` / `progress.retry_fills` when result is `FillResult.APPLIED`; skip `ALREADY_APPLIED`.
- Open question: whether to separate `new_orders_created` into `orders_created` (durable local row), `orders_submitted_confirmed` (broker ACK), and `orders_submission_indeterminate` (timed-out submission). Worth deciding before implementation since it changes the public cycle result shape.

## Touches

- `trade_engine/execution_engine.py` — `process_intent()`, `process_new_intents()`, `sync_broker_state()`, `process_open_orders()`, `CycleProgress`, `run_execution_cycle()`
- `tests/test_fill_hardening.py` — new tests (see Done when)
- `tests/test_trade_engine.py` — may need updates if cycle result key names change

## Done when

- [x] `PENDING_SUBMIT` committed → `submit_order()` timeout → `HALTED` summary shows the local order was created (`orders_created ≥ 1` or equivalent)
- [x] `FILLED` ACK → fill retrieval fails → order activity preserved in summary even though fill count is 0
- [x] `PARTIALLY_FILLED` ACK → fill A applies → fill B throws integrity error → A counted in `fills_on_submission`
- [x] Broker rejects immediately → rejection visible in HALTED summary
- [x] Normal successful submission path produces same metrics as before
- [x] Replayed broker event (`ALREADY_APPLIED`) does not inflate `fills_on_retry` or `total_fills`
- [x] `fills_on_sync` equals the number of fills actually applied during sync, even when sync raises after the first fill
- [x] All 1,454 existing passing tests continue to pass (1,457 pass with 3 new tests)

## Outcome

`CycleProgress` is now truly event-driven across all three stages:

- **process_intent**: Added `_progress` keyword param. `orders_created` incremented before `submit_order()`. `submission_fills` appended for each `APPLIED` fill in FILLED/PARTIALLY_FILLED ACK loops.
- **process_new_intents**: Pass-through of `_progress` to `process_intent`.
- **sync_broker_state**: Added `_progress` param. All three fill paths append to `_progress.sync_fills` / increment `_progress.duplicate_fills_skipped` in-flight. Bulk bulk-assignment in `run_execution_cycle` removed.
- **process_open_orders**: `_progress.retry_fills` only appended when `apply_broker_fill` returns `APPLIED`; `fills` return value retains backward-compat (appends if fill_row exists).
- **CycleProgress**: Added `orders_created` and `submission_fills` fields; `to_summary()` uses them instead of counting from `new_results`.
- One existing test updated: `test_fills_on_submission_counted` — removed wrong `fills_on_retry == 1` assertion for ShadowBroker (shadow applies fills internally → ALREADY_APPLIED → correctly 0).
