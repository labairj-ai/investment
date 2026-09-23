# Replace Cycle Exit Accumulation with Mutable Progress Ledger

- **ID:** 0577
- **Status:** backlog
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

- [ ] Successful new order submitted in `process_new_intents()` → `process_open_orders()` raises `BrokerStateIntegrityError` → submitted order appears in cycle summary (`new_orders_created ≥ 1`)
- [ ] Immediate fill during new-intent submission → later HALT → fill counted in `fills_on_submission`
- [ ] Open-order A fills → open-order B causes integrity HALT → A's fill visible in `fills_on_retry`
- [ ] Open-order A risk-cancelled → B causes HALT → rejection/cancel activity visible in `risk_rejections` / `orders_expired`
- [ ] All-success path produces exactly the same metrics as before this change
- [ ] Existing 0576 tests (`test_sync_fill_preserved_when_*`) still pass unchanged
- [ ] Full suite remains green (`pytest tests/` passes)
