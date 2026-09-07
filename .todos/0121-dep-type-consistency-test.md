# Test: Every Emitted Dependency Type Has a Registered Checker

- **ID:** 0121
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

The prior P0 CC-dependency mismatch (OPTION_EXPIRATION, OPTION_MARK, CC_POSITION_STATE not in the checker's known-type set) was only caught through manual code review. If a new dependency type is added to any agent without a corresponding handler in `dependency_checker.py`, the checker silently fails-safe and supersedes the recommendation — meaning valid recommendations are discarded with no warning.

This class of regression is exactly what a static consistency test prevents. The reviewer explicitly called it out: "I would add a test asserting: every dependency type emitted anywhere under agents/ has a registered dependency checker. That one test would prevent this class of regression permanently."

## Proposed approach

Add `tests/test_dep_type_coverage.py` (or a section in `test_dependency_checker.py`):

1. Scan all `.py` files under `agents/` and `serve.py` for string literals that appear as the `dep_type` argument to `write_dependencies()` or similar calls (regex: `"dep_type":\s*"([A-Z_]+)"` or equivalent AST scan).
2. Import `dependency_checker.KNOWN_DEP_TYPES` (or the equivalent set/dict).
3. Assert every collected type string is in `KNOWN_DEP_TYPES`.

This test runs as part of the existing pytest suite so CI catches future mismatches immediately.

Open question: whether to do regex scan or AST-parse the source. Regex is simpler and sufficient here since dep types are always string literals.

## Touches

- `tests/test_dep_type_coverage.py` (new file)
- `agents/dependency_checker.py` (ensure `KNOWN_DEP_TYPES` is exported as a set constant)

## Done when

- [ ] A pytest test exists that scans agents/ for dep_type string literals
- [ ] The test asserts all found types are in `KNOWN_DEP_TYPES`
- [ ] The test passes on current main (no uncovered types exist)
- [ ] CI runs this test on every push (it is in `tests/`)
