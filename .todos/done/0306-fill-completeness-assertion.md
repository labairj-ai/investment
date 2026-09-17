# Assert Fill Quantity Completeness After Restart Reconciliation

- **ID:** 0306
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0302

## Problem

When `reconcile()` calls `get_fills_for_order()` after `get_order()` reports FILLED or PARTIALLY_FILLED, it blocks if the returned list is empty but does not verify that `sum(f.qty for f in fills)` equals the broker-reported `fill_qty`. A temporarily incomplete Alpaca activities response (e.g. 40 of 100 executed shares visible) would cause the code to apply partial fills and leave the local account with incorrect position and cash balances, with no discrepancy flagged.

## Proposed approach

- After applying fills from `get_fills_for_order()`, compute `observed_qty = sum(f.qty for f in fills)` and compare it against `broker_order.fill_qty`.
- For FILLED orders: `observed_qty` must equal `broker_order.fill_qty` (within a small float tolerance). If not, append `RECONCILIATION_UNAVAILABLE` and do not mark the order as filled.
- For PARTIALLY_FILLED orders: same check — `observed_qty` must equal `broker_order.fill_qty`.
- Apply this check in both the section-3a FILLED path (0302 restart repair) and the section-3c PENDING_SUBMIT FILLED/PARTIALLY_FILLED recovery paths. The `BrokerOrder` returned by `get_order()` already carries `fill_qty`.

## Touches

- `trade_engine/reconciliation.py` — section 3a FILLED path; section 3c PENDING_SUBMIT FILLED/PARTIALLY_FILLED recovery
- `tests/test_trade_engine.py` — new tests for incomplete-fill detection in both paths

## Done when

- [x] Section-3a FILLED path appends `RECONCILIATION_UNAVAILABLE` when `sum(fill.qty) != broker_order.fill_qty`
- [x] Section-3c PENDING_SUBMIT FILLED recovery performs the same check
- [x] Section-3c PARTIALLY_FILLED recovery performs the same check
- [x] Unit tests cover: correct qty passes, incomplete qty blocks, zero-fill (already blocked) unchanged
- [x] All existing tests pass

## Outcome

Added `abs(observed - expected) > 1e-6` fill qty checks in all three reconciliation fill-ingest
paths. On mismatch, appends RECONCILIATION_UNAVAILABLE and sets the fill list to `[]` so the
apply loop is a no-op. Added `test_working_order_filled_incomplete_fills_blocks` and
`test_working_order_filled_complete_fills_passes` to `TestReconciliationRestartRepair`.
705 tests pass.
