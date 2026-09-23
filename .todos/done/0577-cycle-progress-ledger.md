# Replace Cycle Exit Accumulation with Mutable Progress Ledger

- **ID:** 0577
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** none

## Problem

`run_execution_cycle()` accumulates all cycle metrics into local variables and assembles the result dict only at the successful exit path. If `process_open_orders()` raises `BrokerStateIntegrityError` after `process_new_intents()` already submitted a real broker order (or an immediate fill arrived), that submission activity disappears from the cycle summary — the same class of audit hole fixed for sync-stage fills in 0576, but one stage later. A narrower version of the same problem exists inside `process_open_orders()` itself: if it applies a fill for order A and then encounters an integrity failure on order B, A's fill is absent from telemetry even though the economic mutation is committed.

## Proposed approach

- Introduce a `CycleProgress` dataclass (or similar mutable object) instantiated at the top of `run_execution_cycle()`.
- Fields: `sync_fill_ids`, `submission_fill_ids`, `retry_fill_ids`, `new_intents_processed`, `new_orders_created`, `risk_rejections`, `orders_expired`, `broker_seen_ids`, `broker_new_ids`, `broker_duplicate_ids`, `results`.
- Each stage writes into `CycleProgress` as events occur rather than returning accumulated values only on success.
- Every exit path (OK and HALTED) calls `progress.to_summary(execution_state=..., halt_reason=...)` to build the return dict.
- Invariant after this: `HALTED` describes *why* the cycle stopped, not that nothing happened before it stopped.
- Open question: should `process_open_orders()` itself be refactored to update a shared progress object, or should it return partial results even on exception?

## Touches

- `trade_engine/execution_engine.py` — `run_execution_cycle()`, possibly `process_open_orders()`
- `tests/test_fill_hardening.py` — add 5 new test cases (see Done when); existing 0576 tests must still pass

## Done when

- [x] Successful new order submitted in `process_new_intents()` → `process_open_orders()` raises `BrokerStateIntegrityError` → submitted order appears in cycle summary (`new_orders_created ≥ 1`)
- [x] Immediate fill during new-intent submission → later HALT → fill counted in `fills_on_submission`
- [x] Open-order A fills → open-order B causes integrity HALT → A's fill visible in `fills_on_retry`
- [x] Open-order A risk-cancelled → B causes HALT → rejection/cancel activity visible in `risk_rejections` / `orders_expired`
- [x] All-success path produces exactly the same metrics as before this change
- [x] Existing 0576 tests (`test_sync_fill_preserved_when_*`) still pass unchanged
- [x] Full suite remains green (`pytest tests/` passes)

## Outcome

**`trade_engine/execution_engine.py`**:
- Added `from dataclasses import dataclass, field` to imports
- Added `CycleProgress` dataclass (57 lines) just before `run_execution_cycle`: fields for sync, freshness-gate, intent, and open-order stages; `to_summary(execution_state, halt_reason)` builds the result dict from accumulated state
- `process_open_orders()` gains `_progress: Optional[CycleProgress] = None` kwarg; three in-place updates mirror each fill/rejection/expiration into `_progress` before any raise
- `run_execution_cycle()` rewritten to create `progress = CycleProgress()` at entry, populate it after each stage, and call `progress.to_summary(...)` on every exit path (HALTED or OK) — `_HALTED_BASE` and `_sync_earned` dict literals removed

**Invariant achieved**: `HALTED` describes why the cycle stopped; it no longer erases what happened before the stop.

**`tests/test_fill_hardening.py`**: 5 new tests covering all five Done-when scenarios. Full suite: 1454 passed, 0 failed.
