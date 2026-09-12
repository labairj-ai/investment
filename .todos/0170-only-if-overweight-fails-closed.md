# only_if_overweight Gate Fails Closed When Weight Data Missing

- **ID:** 0170
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

In `_check_assignment_eligible()` Gate 5 (`only_if_overweight`), when `ctx.current_weight_pct is None` the condition evaluates to `None < max_position_pct` which is `False` in Python — meaning the gate **fails open** and assignment is allowed as if the position is not overweight. Missing weight data should be treated as an unknown risk, not as safe-to-assign.

This silently bypasses the overweight guard for any position where portfolio weight couldn't be fetched (e.g., first run, stale DB, or API failure).

## Proposed approach

In Gate 5, add an explicit `None` check before the comparison:

```python
if ctx.current_weight_pct is None:
    return EligibilityResult(eligible=False, reason="weight_data_unavailable")
if ctx.current_weight_pct < ctx.max_position_pct:
    return EligibilityResult(eligible=False, reason="only_if_overweight: position not overweight")
```

Also update `ManagementPolicyContext` docstring/field comment to note that `None` means "unavailable" (distinct from 0.0%).

## Touches

- `covered_call_rec.py` — `_check_assignment_eligible()` Gate 5
- `tests/test_cc_management.py` — add test: `only_if_overweight` policy + `current_weight_pct=None` → ineligible

## Done when

- [ ] Gate 5 returns `eligible=False` with reason `weight_data_unavailable` when `current_weight_pct is None`
- [ ] Test: `assignment_policy=only_if_overweight`, `current_weight_pct=None` → not eligible
- [ ] Existing overweight/not-overweight tests still pass
