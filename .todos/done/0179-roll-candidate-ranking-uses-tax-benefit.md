# Feed Tax Benefit Into Roll Candidate Ranking

- **ID:** 0179
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0178

## Problem

`_suggest_next_call()` ranks roll candidates by incremental roll alpha (`cc_alpha − existing_call_mark / NAV`). It does not account for the tax benefit of deferring ST gains to LT status by pushing the roll expiry past relevant LT crossover dates.

Two rolls with identical premiums and deltas may have very different tax impacts: a 45-day roll only passes the nearest LT date; a 75-day roll passes both. The difference in avoidable tax can dwarf the premium spread between candidates.

## Proposed approach

After 0178 introduces `_friction_at_expiry()`, use it inside `_suggest_next_call()` when a `lot_schedule` is available (via `ManagementPolicyContext.tax_friction_detail`):

```python
if ctx.tax_friction_detail and ctx.tax_friction_detail.lot_schedule:
    candidate_exp = date.fromisoformat(candidate["expiration"])
    roll_friction = _friction_at_expiry(
        ctx.tax_friction_detail.lot_schedule,
        ctx.strike,
        candidate_exp,
    )
    tax_benefit = ctx.assignment_tax_friction - roll_friction
    # Add tax_benefit to candidate score or use as tiebreaker
    candidate["tax_benefit_at_expiry"] = round(tax_benefit, 2)
```

The tax benefit can be incorporated as an explicit additive term in the roll alpha or as a secondary sort key when alpha is close. Prefer additive if the units are commensurable (both in dollars of value per contract).

Also: require that a friction-based ROLL recommendation's chosen candidate actually clears the relevant LT dates; if none of the candidates reduce friction, downgrade the recommendation reason.

## Touches

- `covered_call_rec.py` — `_suggest_next_call()`, roll candidate scoring
- `tests/test_covered_call_rec.py` — test: candidate that clears LT dates ranks above one that doesn't, all else equal

## Done when

- [ ] `_suggest_next_call()` computes `tax_benefit_at_expiry` per candidate when `lot_schedule` available
- [ ] Candidates that clear more LT dates rank higher (at minimum as tiebreaker)
- [ ] `next_contract` returned from `evaluate_open_position()` includes `tax_benefit_at_expiry` field
- [ ] Test: identical alpha candidates → LT-clearing one ranks first
- [ ] All existing tests pass
