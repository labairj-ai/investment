# Complete CI Timestamp Enforcement

- **ID:** 0681
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0679

## Problem

`tests/test_ci_datetime_guard.py` currently only blocks `utcnow()` and `utcfromtimestamp()`. It does not detect naive `datetime.now()` (without timezone), fixed Eastern offsets (`timedelta(hours=-4)` / `timedelta(hours=-5)` used as timezone), or hardcoded `"EST"`/`"EDT"` strings — despite 0679 marking all those requirements complete. Seven remaining naive `datetime.now()` calls exist in production code post-batch, two of which are confirmed persistence violations.

## Proposed approach

Make the scanner AST-based or use stronger regex patterns. Catch:

1. `datetime.now()` / `datetime.datetime.now()` without a `tz=` or timezone argument (exclude calls like `datetime.now(TZ_UTC)` or `datetime.now(timezone.utc)`)
2. `datetime.utcnow()` (already caught — keep)
3. `utcfromtimestamp()` (already caught — keep)
4. `timezone(timedelta(hours=-4))` and `timezone(timedelta(hours=-5))` — fixed Eastern offset construction
5. Hardcoded `"EST"` and `"EDT"` as timezone strings (not in comments or test fixtures)

Use AST parsing for (1) to avoid false positives — match `datetime.now()` calls where the argument list is empty or contains no `tz` keyword. Regex is acceptable for (2)–(5) since those patterns are unambiguous.

Add **positive failure tests** for each new prohibited construct — a test that creates a tiny in-memory Python snippet containing the pattern and asserts the guard would flag it. This proves the guard actually enforces what it claims.

Exclusions:
- `time_utils.py` itself
- `tests/` directory
- `scripts/` with documented exceptions
- `migrations/`

## Touches

- `tests/test_ci_datetime_guard.py` — expand patterns; add AST-based `datetime.now()` detection; add positive failure tests per prohibited construct

## Done when

- [x] Guard catches `datetime.now()` without tz argument
- [x] Guard catches `timezone(timedelta(hours=-4/-5))` fixed Eastern offsets
- [x] Guard catches hardcoded `"EST"` / `"EDT"` timezone strings in production code
- [x] Positive failure test: each prohibited pattern makes the guard fail
- [x] `time_utils.py` and test files are correctly excluded
- [x] All existing tests still pass
