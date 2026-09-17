# Apply Reconciliation Tolerances to Runner Divergence Alarm

- **ID:** 0322
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** none

## Problem

`runner.py` logs an ERROR-level alarm when `cash_delta != 0.0` or `position_delta != 0.0`
after reconciliation. Reconciliation itself uses `cash_tolerance=0.01` (1 cent) and
`qty_tolerance=0.0001` (fractional share rounding). The alarm fires on any floating-point
residual — including differences well within those tolerances — producing false alarms
that dilute the signal when a genuine discrepancy occurs.

## Proposed approach

Replace exact-zero comparisons in the divergence alarm with the same thresholds used by
reconciliation:

```python
# Before
if cash_delta != 0.0 or position_delta != 0.0:
    logger.error(...)

# After
if abs(cash_delta) > 0.01 or abs(position_delta) > 0.0001:
    logger.error(...)
```

If `cash_tolerance` and `qty_tolerance` are already named constants, import and reuse
them rather than duplicating the literal values.

## Touches

- `trade_engine/runner.py` — divergence alarm condition

## Done when

- [x] Alarm uses `abs(cash_delta) > 0.01` and `abs(position_delta) > 0.0001`
- [x] Tolerances are either imported from a shared constant or clearly documented as matching reconciliation defaults
- [x] Unit test (or existing test updated): delta within tolerance → no ERROR log; delta outside tolerance → ERROR log

## Outcome

runner.py divergence alarm uses abs(cash_delta) > _CASH_TOLERANCE (0.01) and abs(pos_delta) > _QTY_TOLERANCE (0.0001) matching reconciliation defaults. 718 tests pass.
