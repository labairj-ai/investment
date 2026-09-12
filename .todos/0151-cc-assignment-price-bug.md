# Fix CC Assignment Floor Compares Strike, Not Current Price

- **ID:** 0151
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** high
- **Depends:** none

## Problem

`assignment_eligible()` in `agents/covered_call_agent.py` checks the acceptable-assignment floor with:

```python
if current_price < acceptable_assignment_min_price:
    reject assignment
```

This is wrong. When a call is assigned, the stock is sold at the **strike price**, not at the current market price. If current_price = $205, strike = $180, and the policy floor is $190, the current code says "acceptable" (205 > 190) — but the investor would actually receive $180, which violates the $190 floor.

The correct gate is:

```python
if strike < acceptable_assignment_min_price:
    reject assignment
```

This is a genuine P0 financial-logic bug: it could allow assignment at a price the investor explicitly declared unacceptable.

## Proposed approach

In `assignment_eligible()` (likely around the policy check block), replace the price comparison:

```python
# Before:
if current_price < policy.get("acceptable_assignment_min_price", 0):
    return False, "current price below acceptable floor"

# After:
_floor = policy.get("acceptable_assignment_min_price")
if _floor and strike < _floor:
    return False, f"strike {strike} below acceptable assignment floor {_floor}"
```

Update associated tests in `tests/test_covered_call_agent.py` to use a scenario where current_price > floor > strike (the bug case) and verify it now correctly rejects.

## Touches

- `agents/covered_call_agent.py` — `assignment_eligible()` policy gate
- `tests/test_covered_call_agent.py` — add/update assignment floor test

## Done when

- [ ] Gate compares `strike` (not `current_price`) against `acceptable_assignment_min_price`
- [ ] Test: current_price=205, strike=180, floor=190 → rejected (was incorrectly accepted)
- [ ] Test: current_price=205, strike=195, floor=190 → accepted
- [ ] Existing tests pass
