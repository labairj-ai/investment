# Use Call Expiry Date for Tax Lot Classification

- **ID:** 0168
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`_lot_tax_friction()` calls `is_long_term(purchase_date, today)`, but assignment happens at or after expiry — not today. Any lot that crosses the LT threshold before the call's expiry date will already be long-term when assignment actually occurs. Using today's date causes spurious ST friction reports and drives unnecessary ROLL recommendations.

Concrete case: today Sep 12, call expiry Oct 16, lot goes LT Sep 25. Current code marks it ST → reports friction → may ROLL. Correct: lot is LT at disposal → no friction → ALLOW_ASSIGNMENT.

## Proposed approach

1. Add `disposal_date: date | None = None` parameter to `_lot_tax_friction()`. Default to `date.today()` for backward compat. Replace `is_long_term(purchase_date, today)` with `is_long_term(purchase_date, disposal_date)` and update `days_until_lt()` call similarly.

2. Add `expiry_date: date | None = None` field to `ManagementPolicyContext`.

3. In `_build_mgmt_context_from_db()` (dashboard path): parse the call's expiry string to a `date` and pass it as `disposal_date` to `_lot_tax_friction()`.

4. In `agents/covered_call_agent.py` `_analyze_roll()`: parse existing expiry string to a `date`, populate `ManagementPolicyContext.expiry_date`, and pass it through to `_lot_tax_friction()`.

5. `date.today()` remains the conservative default — for early-exercise scenarios callers can pass a shorter horizon explicitly.

## Touches

- `covered_call_rec.py` — `_lot_tax_friction()` signature, `ManagementPolicyContext`, `_build_mgmt_context_from_db()`
- `agents/covered_call_agent.py` — `_analyze_roll()` context assembly
- `tests/test_cc_management.py` — add tests for lot crossing LT before/after expiry

## Done when

- [ ] `_lot_tax_friction()` accepts `disposal_date` and passes it to `is_long_term()`
- [ ] `ManagementPolicyContext` has `expiry_date: date | None = None` field
- [ ] Agent and dashboard paths populate `expiry_date` from the call's expiry string
- [ ] Test: lot LT on Sep 25, expiry Oct 16 → friction = 0
- [ ] Test: lot LT on Nov 1, expiry Oct 16 → friction > 0
- [ ] All existing tests pass
