# Fix Acceptance Test Escapes and Schema Regressions

- **ID:** 0642
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** none

## Problem

Several tests in `test_portfolio_brief.py` have conditional guards around required contract fields, turning schema regressions into silent passes. Specifically: the Guardian freshness test uses `freshness.get("guardian")` but production emits `freshness["guardian_run"]`, so the assertion body is never reached. Also, test 10 (50-event influence) supplies a synthetic dict with no `capability_state` key to `_format_capability_summary()` rather than calling `build_portfolio_brief_state()`, so it doesn't prove the production path works with real DB data.

## Proposed approach

- Fix Guardian freshness test: replace `guardian_f = freshness.get("guardian")` with a hard assertion `assert "guardian_run" in freshness`, then assert `age_hours`, `status == "STALE"` without any optional `if` guard.
- Remove all `if field:` guards around assertions for fields that are required contract fields. If they're absent, the test should fail loudly.
- Rewrite test 10 to call `build_portfolio_brief_state(conn)` with 50 real events seeded and the acceptance boundary set, then pass the resulting `brief_state` to `_format_capability_summary()` — not a hand-crafted dict.
- Add direct production-path tests for: capability ERROR (seed a broken `_news_intelligence_acceptance` state), thesis ERROR (simulate DB failure in thesis section), learning ERROR (simulate DB failure in learning section), and execution ERROR (simulate DB failure in execution section).

## Touches

- `tests/test_portfolio_brief.py` — fix guardian key, remove conditional guards, rewrite test 10, add four ERROR-path tests

## Done when

- [ ] Guardian freshness test uses `freshness["guardian_run"]` directly and has no `if guardian_f:` guard
- [ ] Test 10 calls `build_portfolio_brief_state()` with a seeded DB rather than a synthetic dict
- [ ] At least one test per major subsystem (capability, thesis, learning, execution) proves that a simulated DB failure sets `status == "ERROR"` on that subsystem dict
- [ ] No test uses optional `if` guards around fields defined as required in the brief contract
