# Add Full Lifecycle and Regression Integration Tests

- **ID:** 0001
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** none

## Problem

The test suite has solid unit coverage for individual modules but no end-to-end test that exercises the full agent pipeline — Snapshot → Trigger → Agent → Recommendation → Critic → Accept → Execute → Outcome Evaluator → Alpha. Without this, regressions in the handoffs between stages (e.g., the JS brace imbalance that broke all tabs, the duplicate `get_todays_findings` that silently killed the daily insight, the `_CRITIC_SCHEMA` format mismatch that invalidated all critic reviews) go undetected until the dashboard breaks in production. There is also no web-layer regression harness to catch generated-HTML or JavaScript errors before deployment.

## Proposed approach

- **Backend lifecycle test** (`tests/test_lifecycle.py` — extend or replace stub):
  - Build a minimal in-memory SQLite fixture with a single holding (e.g., ANET or EW)
  - Drive the full pipeline: `build_portfolio_snapshot` → `detect_triggers` → run sell/trim agent → `run_critic_agent` → simulate user Accept → `insert_executed_action` → `run_outcome_evaluator`
  - Assert: recommendation created, critic review written with real verdict (not fallback), outcome row written with non-null `hold_return` and `spy_return`
  - **Edge case**: Accept an EXIT recommendation but insert no execution → assert `actual_return IS NULL` and `actual_is_estimated = 1`, not `actual_return = 0.0`
  - **Edge case**: TRIM accepted without execution → assert `actual_is_estimated = 1`
- **Schema/JS regression test** (`tests/test_dashboard_js.py`):
  - Call `generate_dashboard.py` against a fixture DB and run `node --check` on the output HTML's script blocks
  - Assert brace balance (open `{` count equals close `}` count per script block)
  - Assert `ollama_client.generate_structured` called with a flat schema dict (keys are expected output fields, not JSON Schema meta-keys like `type`/`properties`/`required`)
- **Agent DB function signature test**:
  - Assert `agent_db.get_todays_findings()` returns a `dict` with keys `findings` and `recommendations` (guards against duplicate-definition shadowing)
  - Assert `agent_db.get_recent_findings()` returns a `list`
- **Web smoke test** (manual checklist or lightweight Playwright script):
  - Dashboard loads without console errors
  - All tabs navigate correctly (Portfolio, Decisions, Dividends, Goals, Tax)
  - Decision queue shows real critic verdicts, not the "LLM unavailable" fallback string

## Touches

- `tests/test_lifecycle.py`
- `tests/test_dashboard_js.py` (new)
- `tests/test_agent_db.py`
- `generate_dashboard.py`
- `agents/critic_agent.py`
- `agents/outcome_evaluator.py`
- `agent_db.py`
- `ollama_client.py`

## Done when

- [ ] `pytest tests/test_lifecycle.py` passes and exercises Snapshot→Trigger→Agent→Critic→Accept→Execute→Outcome in one fixture
- [ ] Lifecycle test asserts accepted-EXIT-without-execution produces `actual_return = NULL`, not `0.0`
- [ ] `pytest tests/test_dashboard_js.py` runs `node --check` on generated script blocks and asserts brace balance
- [ ] `pytest tests/test_agent_db.py` asserts `get_todays_findings` return type is `dict` with correct keys
- [ ] All new tests pass in CI (`pytest tests/` green)
- [ ] Manual web smoke: dashboard loads, all 5 tabs navigate, decision queue shows real LLM verdicts
- [ ] Regression: re-running tests after reverting any of the three bug fixes from 2026-09-07 causes at least one test to fail
