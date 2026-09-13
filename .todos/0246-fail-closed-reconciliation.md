# Fail-Closed Reconciliation — Retrieval Failures Block Submission

- **ID:** 0246
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0240

## Problem

`reconcile()` silently swallows `get_positions()` and `get_open_orders()` failures with bare `except: pass`. A broker connectivity error during reconciliation therefore produces a result that looks safe enough to trade — the missing data registers as zero discrepancies rather than an error. Additionally, open-order comparison is only unidirectional (local vs. broker); broker orders not present locally are not detected. Unresolved position quantity mismatches do not block submission.

## Proposed approach

1. Add `DiscrepancyKind.RECONCILIATION_UNAVAILABLE` — returned when any retrieval call (cash, positions, orders) raises an exception.
2. Add `RECONCILIATION_UNAVAILABLE` to `_BLOCKING_KINDS`. Any retrieval failure → `blocks_submission=True`.
3. Make position/order reconciliation bidirectional:
   - Local missing at broker → `BROKER_MISSING` (already done for orders; add for positions)
   - Broker order/position not in local DB → `LOCAL_MISSING` (currently only noted, not blocking)
4. After fill import completes, promote `QUANTITY_MISMATCH` to a blocking kind — an unexplained position mismatch in a real-money account should prevent new orders.
5. Remove all `except: pass` in `reconcile()`. Let exceptions surface as `RECONCILIATION_UNAVAILABLE` discrepancies.

## Touches

- `trade_engine/reconciliation.py`
- `tests/test_trade_engine.py` (or new `tests/test_reconciliation.py`)

## Done when

- [ ] `get_positions()` or `get_open_orders()` failure produces `RECONCILIATION_UNAVAILABLE` discrepancy that blocks submission
- [ ] Position comparison is bidirectional (broker-only positions detected as `LOCAL_MISSING`)
- [ ] `QUANTITY_MISMATCH` blocks submission after fill import completes
- [ ] No bare `except: pass` remains in `reconcile()`
- [ ] Tests simulate broker retrieval failure and assert `blocks_submission=True`
