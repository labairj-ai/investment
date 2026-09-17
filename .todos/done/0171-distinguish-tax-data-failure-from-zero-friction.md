# Distinguish Tax-Data Failure from Zero Friction

- **ID:** 0171
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`_lot_tax_friction()` returns `(0.0, "no lots found")` when `select_fifo_lots()` returns an empty list. Callers (and the dashboard) see `assignment_tax_friction = 0.0` and treat it as "no friction" — identical to a position fully in long-term lots. But "no lots found" is actually a data error: every assigned position must have at least one lot. Silently returning zero friction when lot data is missing can cause Gate 4 to allow assignment on a position whose true tax cost is unknown.

## Proposed approach

Return a sentinel `float('nan')` (or raise a custom `TaxDataError`) when `select_fifo_lots()` returns empty. Gate 4 in `_check_assignment_eligible()` should treat `nan` (or catch `TaxDataError`) as ineligible with reason `tax_data_unavailable`.

Alternatively, introduce a `tax_friction_available: bool` field on `ManagementPolicyContext` (defaulting to `True`) and set it `False` when lot lookup fails; Gate 4 checks `available` first.

Prefer the `nan` sentinel if it keeps the change local to `_lot_tax_friction()` and Gate 4; use the struct field if callers need to distinguish the cause in reporting.

## Touches

- `covered_call_rec.py` — `_lot_tax_friction()`, Gate 4 in `_check_assignment_eligible()`
- `tests/test_cc_management.py` — test: empty lots → Gate 4 blocks assignment
- `tests/test_cc_management.py` — test: LT lots → friction=0.0, `available=True` (or non-nan) → gate passes

## Done when

- [ ] Empty lot list → assignment ineligible with reason `tax_data_unavailable` (not silently zero)
- [ ] LT lots → friction = 0.0 → assignment still eligible when policy allows
- [ ] Test covering both cases passes
- [ ] All existing tests pass
