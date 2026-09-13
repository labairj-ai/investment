# Fix PARTIALLY_FILLED Branch in PENDING_SUBMIT Recovery Reducer

- **ID:** 0279
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0274, 0273

## Problem

The 0274 story specified that a broker-reported `PARTIALLY_FILLED` state during PENDING_SUBMIT recovery should ingest authoritative fills and leave the order locally as `PARTIALLY_FILLED`. The implementation instead collapses `PARTIALLY_FILLED` into the same `if _bstate in ("WORKING", "PARTIALLY_FILLED")` branch that writes `state='WORKING'` and fetches no fills. A restart after a partial fill therefore produces a WORKING order with no position and wrong cash balance — a state where risk evaluation runs against incorrect account data. The normal fill query may eventually rescue this, but that rescue path is not guaranteed and the reducer itself violates the contract it was designed to enforce.

## Proposed approach

- Split `PARTIALLY_FILLED` out of the `("WORKING", "PARTIALLY_FILLED")` branch in reconciliation section 3c.
- `PARTIALLY_FILLED` branch: attach `broker_order_id`, call `get_fills_for_order()`, apply each returned fill idempotently via `apply_broker_fill()`, do not manually set a final state — let the aggregate fill ledger determine whether the result is `PARTIALLY_FILLED` or (unexpectedly) `FILLED`.
- Do not explicitly write `state='PARTIALLY_FILLED'` — trust `apply_broker_fill()` to update order state as fills are ingested, same as every other fill path.
- Add chaos test: submit intent → `BrokerSubmissionIndeterminate` → broker partially fills before restart → restart + `run_reconciliation()` → assert order is `PARTIALLY_FILLED`, position reflects partial qty, cash reflects partial cost, intent is not FILLED, no resubmission occurred.

## Touches

- `trade_engine/reconciliation.py` — section 3c: separate PARTIALLY_FILLED from WORKING branch; add get_fills_for_order() call
- `tests/test_chaos.py` — partial-fill-before-restart scenario in `TestTerminalStateRecovery` or new class

## Done when

- [ ] `PARTIALLY_FILLED` has its own branch in section 3c; `("WORKING", "PARTIALLY_FILLED")` collapsed branch removed
- [ ] Branch calls `get_fills_for_order()` and applies each fill via `apply_broker_fill()`; no explicit state write
- [ ] Chaos test: broker partially filled before restart → PARTIALLY_FILLED with correct partial position and cash
- [ ] Chaos test asserts zero resubmissions
- [ ] All existing 566 tests still pass
