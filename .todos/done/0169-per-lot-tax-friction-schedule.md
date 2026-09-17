# Per-Lot Tax Friction Schedule by LT Date

- **ID:** 0169
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0168

## Problem

`_lot_tax_friction()` returns a single scalar (total friction in dollars) and a single reason string. When a position has multiple lots at different holding periods, the caller has no way to know which lots drove the friction or when each lot crosses to LT. This prevents the CC recommendation engine from suggesting "wait N days and the friction drops by $X" or displaying a friction timeline in the dashboard.

## Proposed approach

Extend `_lot_tax_friction()` to return a structured result alongside the scalar, e.g.:

```python
@dataclass
class TaxFrictionDetail:
    total_friction: float
    reason: str
    lot_schedule: list[dict]   # [{purchase_date, allocated_shares, lt_date, friction_if_disposed_today}]
```

- `lot_schedule` is ordered FIFO (same order as `select_fifo_lots`).
- Each entry carries `lt_date` (from `lt_threshold(purchase_date)`) and `friction_if_disposed_today` for that lot alone.
- Callers that only need the scalar use `result.total_friction` — backward-compatible.
- Expose `lot_schedule` to the dashboard JSON so the UI can render a timeline.

Keep the implementation in `covered_call_rec.py`; no new file needed.

## Touches

- `covered_call_rec.py` — `_lot_tax_friction()`, possibly `ManagementPolicyContext` to carry the schedule
- `tests/test_cc_management.py` — test that `lot_schedule` has correct entries for a multi-lot scenario

## Done when

- [ ] `_lot_tax_friction()` returns `TaxFrictionDetail` with `lot_schedule` populated
- [ ] Existing scalar callers still work (access `.total_friction`)
- [ ] `lot_schedule` entries have `purchase_date`, `allocated_shares`, `lt_date`, `friction_if_disposed_today`
- [ ] Test: two lots at different maturities → correct per-lot breakdown
- [ ] All existing tests pass
