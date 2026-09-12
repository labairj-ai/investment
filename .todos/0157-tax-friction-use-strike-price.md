# Fix Tax Friction to Use Strike as Assignment Price

- **ID:** 0157
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`_lot_tax_friction(ticker, current_price)` in `covered_call_rec.py` computes each lot's gain as `shares * (current_price - cost_per_share)`. When a covered call is assigned, shares are sold at the **strike**, not the current market price.

Concrete example: ANET current price $205, strike $180, basis $150. Current code computes $5,500 ST gain; actual assignment creates $3,000 ST gain — a 45% overstatement of tax friction that can produce spurious ROLL recommendations when assignment would be correct.

## Proposed approach

Change the signature to:
```python
def _lot_tax_friction(
    ticker: str,
    assignment_price: float,   # = strike, not current market price
    shares_to_assign: int,     # contracts × 100
) -> tuple[float, str]:
```

Thread `strike` and `contracts * 100` through the call chain:
- `evaluate_cc_management_state()` gains a `contracts: int = 1` parameter
- `_check_assignment_eligible()` gains a `contracts: int` parameter, passes to `_lot_tax_friction`
- `_analyze_roll()` in `covered_call_agent.py` passes `contracts` to `evaluate_cc_management_state()`

## Touches

- `covered_call_rec.py` — `_lot_tax_friction()` signature + gain calculation; `_check_assignment_eligible()` signature; `evaluate_cc_management_state()` signature
- `agents/covered_call_agent.py` — `_analyze_roll()` call to `evaluate_cc_management_state()`
- `tests/test_covered_call_agent.py` or `tests/test_covered_call_rec.py` — new test: current_price=$205, strike=$180, basis=$150 → gain uses $180, not $205

## Done when

- [ ] Gain computed as `shares × (strike − cost_per_share)` not `shares × (current_price − cost_per_share)`
- [ ] `_check_assignment_eligible()` accepts and threads `contracts` → `_lot_tax_friction()`
- [ ] `evaluate_cc_management_state()` signature includes `contracts` and passes through
- [ ] `_analyze_roll()` passes `contracts` from position payload
- [ ] Existing tests pass; new test confirms strike-based calculation
