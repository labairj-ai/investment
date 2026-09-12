# only_if_overweight Fails Closed When max_position_pct Is None

- **ID:** 0177
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

Gate 5 was fixed (0170) to block assignment when `current_weight_pct is None`. But the symmetric case remains:

```python
if ctx.current_weight_pct is None:
    return False, "weight_data_unavailable: ..."
if ctx.max_position_pct is not None and ctx.current_weight_pct <= ctx.max_position_pct:
    return False, "not overweight ..."
```

When `only_if_overweight = True`, `current_weight_pct = 12%`, and `max_position_pct = None`, the second condition short-circuits to False and the gate **passes silently** — the position could be at any weight relative to any threshold, and the policy is effectively disabled.

If the user explicitly configured `only_if_overweight = True`, both values are required to enforce the rule. A missing max makes the threshold unknowable, which should fail closed.

## Proposed approach

Replace the compound condition with explicit guards:

```python
if asgn_policy.get("only_if_overweight", False):
    if ctx.current_weight_pct is None:
        return False, "weight_data_unavailable: cannot assess overweight status"
    if ctx.max_position_pct is None:
        return False, "max_position_pct_unavailable: cannot assess overweight status"
    if ctx.current_weight_pct <= ctx.max_position_pct:
        return False, (
            f"not overweight ({ctx.current_weight_pct:.1f}% vs "
            f"{ctx.max_position_pct:.1f}% max) — assignment would reduce below target"
        )
```

## Touches

- `covered_call_rec.py` — `_check_assignment_eligible()` Gate 5
- `tests/test_cc_management.py` — add test: `only_if_overweight=True`, `current_weight_pct=12`, `max_position_pct=None` → not eligible with "unavailable" reason

## Done when

- [ ] Gate 5 blocks when `max_position_pct is None` under `only_if_overweight=True`
- [ ] Reason string contains "unavailable"
- [ ] Existing `current_weight_pct is None` test still passes
- [ ] New test: `max_position_pct=None` + `only_if_overweight=True` → ineligible
- [ ] All other existing tests pass
