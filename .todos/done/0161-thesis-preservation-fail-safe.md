# Conservative Fallback When Thesis Health Is Unavailable Under preserve_high_conviction

- **ID:** 0161
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

In Gate 5 of `_check_assignment_eligible()`, when `preserve_high_conviction=True`:
- If `get_active_thesis()` returns `None` (no thesis) → gate falls through → assignment allowed
- If thesis exists but `pillars` have no scored entries (`scored = []`) → `health` is never computed → gate falls through → assignment allowed

In both cases the gate silently permits ALLOW_ASSIGNMENT even though the policy was explicitly set to preserve a high-conviction holding. The cost of spuriously blocking one assignment cycle is small; the cost of calling away a deliberate long-term compounder because the thesis data failed to load is much larger.

## Proposed approach

Invert the fail-safe: when `preserve_high_conviction=True` and thesis health **cannot be reliably determined**, block assignment and return a ROLL reason:

```python
if asgn_policy.get("preserve_high_conviction", False):
    thesis = get_active_thesis(ticker)
    if thesis is None:
        return False, "preserve_high_conviction: no active thesis found — deferring to ROLL"
    scored = [p for p in thesis.get("pillars", []) if p.get("score") is not None]
    if not scored:
        return False, "preserve_high_conviction: thesis pillar scores unavailable — deferring to ROLL"
    # ... existing health computation
```

Only allow assignment when the system can **positively confirm** that thesis health is below the preservation threshold. Unknown = conservative.

## Touches

- `covered_call_rec.py` — `_check_assignment_eligible()` Gate 5: add fail-safe returns for missing thesis and missing pillar scores
- `tests/test_covered_call_agent.py` — test: `preserve_high_conviction=True`, thesis=None → ROLL; test: thesis exists, no scored pillars → ROLL; test: thesis with scored pillars below threshold → ALLOW_ASSIGNMENT still works

## Done when

- [ ] `preserve_high_conviction=True` + no active thesis → ROLL (not ALLOW_ASSIGNMENT)
- [ ] `preserve_high_conviction=True` + thesis exists but no scored pillars → ROLL
- [ ] `preserve_high_conviction=True` + thesis health clearly below threshold → ALLOW_ASSIGNMENT unchanged
- [ ] `preserve_high_conviction=False` (default) → no behavior change
- [ ] Existing tests pass
