# Calculate Tax Friction at Each Roll Candidate Expiry

- **ID:** 0178
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0174, 0176

## Problem

The current `_lot_tax_friction()` calculates ST tax cost as a single number using the current call's expiry as the disposal date. This tells us what friction looks like at the *current* expiry but not at a *replacement* expiry.

Consider:
- 50 shares → LT in 10 days (current call expires in 5 days, roll expiry 30 days out)
- 50 shares → LT in 70 days (roll expiry 30 days out still can't protect these)

The current logic recommends rolling to avoid the full 100-share ST friction, but a 30-day roll only defers 50 shares past LT — the other 50 are still ST at the replacement expiry. The roll saves *half* the claimed friction. If that half is below the threshold, the roll recommendation was wrong.

The `lot_schedule` already carries `lt_date` per lot (added in 0169), so the information is available — it just isn't being used to evaluate roll candidates.

## Proposed approach

Add a helper `_friction_at_expiry(lot_schedule, assignment_price, candidate_expiry_date)` that recomputes friction using `candidate_expiry_date` as the disposal date rather than the current expiry:

```python
def _friction_at_expiry(
    lot_schedule: list[dict],
    assignment_price: float,
    candidate_expiry: date,
) -> float:
    """Return avoidable tax dollars if assignment occurs at candidate_expiry."""
    from tax_utils import is_long_term as _is_lt
    st_gain = 0.0
    for entry in lot_schedule:
        purchase_date = date.fromisoformat(entry["purchase_date"])
        allocated = entry["allocated_shares"]
        gain = allocated * (assignment_price - entry.get("cost_per_share", assignment_price))
        if gain > 0 and not _is_lt(purchase_date, candidate_expiry):
            st_gain += gain
    return st_gain * (TAX_ST_RATE - TAX_LT_RATE)
```

Then in `evaluate_cc_management_state()` or `_suggest_next_call()`, when evaluating a roll candidate with expiry `candidate_exp`:

```python
roll_friction = _friction_at_expiry(ctx.tax_friction_detail.lot_schedule, ctx.strike, candidate_exp)
roll_friction_reduction = ctx.assignment_tax_friction - roll_friction
```

If `roll_friction_reduction <= 0` (rolling provides no tax benefit), the friction-based ROLL recommendation is not justified.

Store `cost_per_share` in `lot_schedule` entries (currently missing — lot_schedule has `purchase_date`, `allocated_shares`, `lt_date`, `friction_contribution` but not `cost_per_share`).

## Touches

- `covered_call_rec.py` — `_lot_tax_friction()` to add `cost_per_share` to `lot_schedule` entries; add `_friction_at_expiry()` helper; call site in ROLL decision path
- `tests/test_cc_management.py` — test: lot crossing LT at 30d but not 10d → friction at 30d < friction at current expiry

## Done when

- [ ] `lot_schedule` entries include `cost_per_share`
- [ ] `_friction_at_expiry(lot_schedule, assignment_price, candidate_expiry)` helper exists and is tested
- [ ] Roll candidate evaluation uses `_friction_at_expiry` to verify the roll actually reduces friction
- [ ] Test: mixed LT-crossover dates, short roll expiry → friction not fully avoided → ROLL not justified
- [ ] All existing tests pass
