# Fix Integrity Rollup to Treat Error Status as Failing

- **ID:** 0459
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** none

## Problem

`check_integrity.py` aggregates individual check results but only looks for `BLOCK` and `WARN` statuses when computing the overall result. If an individual check throws an exception it is recorded as `status="error"`, but because `error` is not in the aggregation logic, the final rollup can still produce `overall="ok"`. This means a broken integrity check silently passes rather than failing closed — undermining the acceptance guarantee that 0457 depends on.

## Proposed approach

- Change the rollup in `check_integrity.py` to use this priority order:
  - any `BLOCK` → overall `BLOCK`
  - any `error` → overall `error`
  - any `WARN` → overall `WARN`
  - otherwise → `ok`
- The acceptance script already requires `integrity_overall == "ok"`, so surfacing `error` at the rollup level is sufficient to block acceptance without changing the acceptance script itself.
- Add a test that injects a check which raises an exception and asserts that (a) overall integrity is `error`, and (b) running acceptance against that result does not produce PASS.

## Touches

- `Desktop/investment/check_integrity.py` (rollup logic)
- `Desktop/investment/tests/` (new test for thrown-check → error → acceptance blocked)

## Done when

- [ ] `check_integrity.py` rollup marks overall as `error` when any individual check raises
- [ ] Acceptance script rejects a run whose integrity overall is `error`
- [ ] Test covers: one check throws → integrity overall == "error" → acceptance cannot PASS
