# Add End-to-End Lifecycle Integration Tests

- **ID:** 0081
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0070, 0071, 0072

## Problem

The current test suite has 50 unit tests covering individual functions (snapshot building, score math, DB CRUD, scenario return calculations). There are no integration tests covering the full recommendation lifecycle: Trigger → Agent → Recommendation → Critic → User Decision → Execution → Outcome Evaluation → Decision Quality. Without these, regressions in the inter-component wiring are invisible until production. This is the highest-value test gap now that the architecture is substantially built.

## Proposed approach

Write 8–12 lifecycle tests using the existing `mem_db` and `mock_llm` fixtures. Each test seeds the DB with realistic state, runs the pipeline, and asserts on the resulting DB rows.

Suggested scenarios:
1. **HOLD lifecycle** — trigger → recommendation → accept → mature → outcome (hold return = SPY return)
2. **TRIM with execution** — trigger → TRIM rec → accept → execute (partial) → mature → outcome uses execution_fraction, not 0.5
3. **EXIT accepted with execution** — actual_return from execution_price; actual_is_estimated = False
4. **EXIT accepted without execution** — actual_return = None; actual_is_estimated = True
5. **Rejected recommendation** — actual_return = hold_return; actual_is_estimated = False
6. **CC recommendation** — SELL_CC → execution with real premium/strike → outcome uses actual CC path
7. **Dependency supersession** — PRICE dependency, price moves 6%, recommendation is superseded
8. **Critic auto-run** — producers run → critic auto-fires → verdict recorded → briefing synthesizes
9. **Decision Quality gate** — n < 10 outcomes → note not surfaced; n ≥ 10 with tight CI → note surfaced
10. **Cooldown enforcement** — second rec for same ticker/action within 5 days is skipped

Each test should use the `mem_db` fixture and `mock_llm` autouse fixture. Price history for outcome evaluation should be seeded directly into `holding_day`.

## Touches

- `tests/test_lifecycle.py` (new)
- Existing fixtures in `tests/conftest.py` — may need a `seed_holding_day()` helper
- Possibly `agents/orchestrator.py` to expose `run_agents()` return values (see 0079)

## Done when

- [ ] `tests/test_lifecycle.py` exists with at least 8 scenario tests
- [ ] All 8 scenarios pass in CI
- [ ] At least one test covers the full trigger → outcome → decision-quality path
- [ ] Tests run in under 5 seconds total (no LLM calls, no network)
