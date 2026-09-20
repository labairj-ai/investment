# Distinguish NO_SWEEP From DB Query Failure

- **ID:** 0462
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** none

## Problem

Both sweep locators catch `sqlite3.OperationalError` and return `None`, which the runner interprets as NO_SWEEP and exits 2 ("too early — check back later"). A schema mismatch, missing table, or corrupt database is therefore silently presented to the operator as "no qualifying sweep yet" rather than a hard failure. The acceptance script should only claim it is too early when it successfully queried the database and found no qualifying row.

## Proposed approach

- Introduce a sentinel or exception type to distinguish the two outcomes from the sweep locators:
  - Successful query, no qualifying row → NO_SWEEP → exit 2
  - `sqlite3.OperationalError` (or any query failure) → DB_ERROR → exit 1 or 3
- Raise (or re-raise) DB errors rather than absorbing them into `None`, or use a named return value (`NoSweep` vs `DbError`) the runner can branch on.
- Add tests for both locators: one that simulates a schema error and asserts exit code is not 2, and one that simulates an empty result set and asserts exit code is 2.

## Touches

- `Desktop/investment/` — sweep locator functions and runner exit-code logic (exact filenames unknown)
- `Desktop/investment/tests/` — new tests distinguishing DB error from absent sweep

## Done when

- [ ] A `sqlite3.OperationalError` during sweep lookup produces a hard-failure exit (not exit 2)
- [ ] An empty but successfully-queried DB still produces exit 2
- [ ] Tests cover both paths for each sweep locator
