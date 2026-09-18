# Make Post-Insert COUNT Failure Abort the Sweep

- **ID:** 0431
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0425

## Problem

After observations are inserted, `score_for_observe()` does a `COUNT(*)` to get the authoritative persisted row count. If that COUNT query throws, the code silently falls back to the attempted-insert counter (`n_written`), which can include INSERT OR IGNORE no-ops — reintroducing the exact overcounting bug 0425 was meant to fix. Separately, `final_status = "COMPLETED" if actual_count >= expected` accepts `actual > expected` as healthy, but an observation count that exceeds what the sweep declared is an integrity error, not a success.

## Proposed approach

- Remove the `except: pass` around the post-insert COUNT. On failure: set ledger status to `FAILED`, record the error string, and raise so the caller logs it.
- Change the status assignment to three-way:
  - `actual == expected` → `COMPLETED`
  - `actual < expected` → `PARTIAL`
  - `actual > expected` → `FAILED` (or a new `INCONSISTENT` status)
- Update `_check_candidate_coverage()` in `check_integrity.py` to treat `actual > expected` rows as BLOCK-level violations.

## Touches

- `agents/learning/challenger.py` — post-insert COUNT block and `final_status` logic
- `check_integrity.py` — `_check_candidate_coverage()` query/status mapping
- `tests/test_calibration.py` — new tests for COUNT failure → FAILED + raise; actual > expected → FAILED

## Done when

- [ ] COUNT query failure sets ledger status FAILED and raises (no silent fallback)
- [ ] `actual > expected` produces FAILED/INCONSISTENT ledger status, not COMPLETED
- [ ] `_check_candidate_coverage()` surfaces `actual > expected` rows as BLOCK
- [ ] Tests cover all three branches: exact match, under, over
