# Fix Persisted Dimension Eligibility Semantics

- **ID:** 0543
- **Status:** backlog
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0541

## Problem

The accepted-validation `eligible` column is added through a generic TEXT migration, while activation writes numeric values and `_accepted_dim_state()` uses `bool(row[4])`. SQLite can store `0` as text and Python treats `bool("0")` as true, allowing an unstable dimension to become formally usable after persistence.

## Proposed approach

- Rebuild or migrate the accepted-validation table so `eligible` is INTEGER with a `CHECK (eligible IN (0,1))` constraint.
- Read eligibility explicitly as `row_value == 1`, with an explicit legacy NULL policy.
- Preserve existing validation rows and make migration idempotent.
- Add database round-trip tests for eligible 1, eligible 0, and eligible NULL.

## Touches

- `portfolio_ai.py` schema migration and `_accepted_dim_state()`
- Acceptance persistence tests

## Done when

- [ ] Persisted false eligibility can never read back as usable.
- [ ] The schema enforces integer 0/1 values for new rows.
- [ ] Legacy NULL behavior is explicit and tested.
- [ ] Existing databases migrate without losing accepted-validation history.
