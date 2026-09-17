# Repair Terminal Orders on Restart Before Declaring BROKER_MISSING

- **ID:** 0302
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0297

## Problem

After a restart, a local WORKING or PARTIALLY_FILLED order whose broker state became CANCELLED, REJECTED, or EXPIRED while the app was down is absent from `broker.get_open_orders()`. Reconciliation currently treats "local WORKING, absent from broker open-orders list" as `BROKER_MISSING` and halts the cycle. This is safe but brittle for an unattended system: a cleanly-expired DAY order will always require manual intervention to clear, even though its terminal state is unambiguous from the broker's perspective.

## Proposed approach

In the reconciliation section that checks local WORKING/PARTIALLY_FILLED orders against the broker open-orders list, add a lookup step before declaring `BROKER_MISSING`:

1. If the local order has a `broker_order_id`, call `broker.get_order(broker_order_id)`.
2. Route on the result:
   - **FILLED** → ingest fills via `get_fills_for_order()` and apply each with `apply_broker_fill()`; mark local order FILLED.
   - **CANCELLED / REJECTED / EXPIRED** → update local order state to match; no fill ingestion needed.
   - **Still open (WORKING / PARTIALLY_FILLED)** → treat as a genuine reconciliation discrepancy (current BROKER_MISSING behavior).
   - **Not found (None) or request failure** → HALT; do not infer state from absence.
3. Only declare `BROKER_MISSING` after the lookup fails to resolve the discrepancy, not as the first response to a missing order.

## Touches

- `trade_engine/reconciliation.py` — section 3a, local→broker check for WORKING/PARTIALLY_FILLED
- `tests/test_trade_engine.py` — new `TestReconciliationRestartRepair` class

## Done when

- [x] A local WORKING order with a known `broker_order_id` that is absent from broker open orders triggers `broker.get_order()` before `BROKER_MISSING` is declared
- [x] Broker returns CANCELLED → local order updated to CANCELLED; no halt
- [x] Broker returns EXPIRED → local order updated to EXPIRED; no halt
- [x] Broker returns FILLED → fills ingested via `get_fills_for_order()` + `apply_broker_fill()`; no halt
- [x] Broker returns still-open state → existing BROKER_MISSING halt behavior preserved
- [x] Broker returns None or raises → HALT (never infer terminal state from absence)
- [x] All existing tests pass

## Outcome

Added `broker_order_id` to the local_open_rows query. When a WORKING order is absent from
broker open-orders, the reconciler now calls `broker.get_order(broker_oid)` and routes:
CANCELLED/REJECTED/EXPIRED → DB update + intent status update, no discrepancy; FILLED → fill
ingest path (same as PENDING_SUBMIT FILLED recovery); still-open → BROKER_MISSING; None →
BROKER_MISSING; exception → RECONCILIATION_UNAVAILABLE; no broker_order_id → BROKER_MISSING.
Added `TestReconciliationRestartRepair` with 6 tests. 702 tests pass.
