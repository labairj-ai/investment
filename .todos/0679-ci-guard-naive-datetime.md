# CI Guard Against Naive Datetime Usage

- **ID:** 0679
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** none

## Problem

Without automated enforcement, new code can reintroduce naive datetime patterns (`datetime.now()`, `datetime.utcnow()`, `utcfromtimestamp()`, fixed EST offsets, manual hour subtraction) that violate the timestamp contract. The violation may go unnoticed until a DST transition or server move reveals it in production.

## Proposed approach

Add a CI check (pre-commit hook, linter rule, or test) that fails on these patterns in production code:

- `datetime.now()` without timezone argument
- `datetime.utcnow()`
- `utcfromtimestamp()`
- Fixed EST/EDT timezone strings or `timedelta(hours=-5)` / `timedelta(hours=-4)` used as timezone representations
- Timestamp string comparisons where datetime comparison is required (e.g. `ts_str > cutoff_str`)

Allow exceptions only via an explicit suppression comment. Exclude test files and migration scripts via documented exception patterns. Exclude canonical time utilities themselves.

## Touches

- `.pre-commit-config.yaml` or `pyproject.toml` (lint rules)
- Or `tests/test_ci_guard.py` using `ast` module to scan production source
- `time_utils.py` — exclusion pattern

## Done when

- [x] CI fails when a new naive `datetime.now()` is added to production code
- [x] CI fails on `datetime.utcnow()`
- [x] CI flags fixed-offset Eastern conversions
- [x] Tests and migrations may use documented exceptions
- [x] Canonical time utilities themselves are excluded appropriately
## Outcome

Implemented as part of 0668-0680 batch commit.
