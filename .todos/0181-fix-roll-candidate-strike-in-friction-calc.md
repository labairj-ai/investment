# Fix Roll Candidate Strike in Tax Friction Calculation

- **ID:** 0181
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`_suggest_next_call()` calls `_friction_at_expiry()` using the *existing* call's strike as `assignment_price`, not the candidate's strike (`s`). This is economically wrong.

If a candidate roll has a higher strike than the current one, assignment at that higher strike produces a larger gain — and potentially more short-term tax friction — than the current code assumes. Understating that friction overstates the apparent tax benefit of rolling out, which can produce an incorrect roll recommendation.

Concrete example (from reviewer):
- Existing strike: $180, candidate strike: $195, cost basis: $150
- At assignment: gain is 100 × ($195 − $150) = $4,500 per lot
- Current code calculates friction using $180 → 100 × ($180 − $150) = $3,000 understatement

## Proposed approach

Inside the candidate loop in `_suggest_next_call()`, change:

```python
roll_friction = _friction_at_expiry(lot_schedule, assignment_price, exp_date)
```

to:

```python
roll_friction = _friction_at_expiry(lot_schedule, s, exp_date)
```

where `s` is the candidate strike already in scope. The existing `assignment_price` parameter becomes only a fallback / documentation artifact; after this fix it is no longer used in the friction calc.

## Touches

- `covered_call_rec.py` — `_suggest_next_call()` candidate loop (~line 1407)
- `tests/test_cc_management.py` — add test: candidate at higher strike produces higher friction than existing-strike calc

## Done when

- [ ] `_friction_at_expiry()` receives candidate strike `s`, not existing `assignment_price`
- [ ] Test: existing strike $180, candidate $195, cost $150, ST lot → candidate friction > existing friction
- [ ] All existing tests pass
