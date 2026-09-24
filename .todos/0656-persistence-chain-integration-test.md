# Persistence-Chain Integration Test

- **ID:** 0656
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0655, 0653

## Problem

`test_real_state_canary` exercises `build_portfolio_brief_state()` + `_apply_brief_policy()` but never calls `create_portfolio_brief()`. The full persistence chain — `_run_briefing_llm()` → `_apply_brief_policy()` → `portfolio_brief_snapshots` → `ai_insights` → `portfolio_brief_provenance` → `source_refs_json` — has no test. The commit description claimed this was validated, but it was not.

Concretely, there is no test that:
- Verifies `ai_insights`, `portfolio_brief_snapshots`, and `portfolio_brief_provenance` all receive the same `portfolio_state` after policy correction
- Verifies `source_refs_json` in provenance actually points to the Guardian/recommendation/news source IDs seeded in the fixture
- Exercises the scenario where the LLM returns a wrong state and policy corrects it before persistence (so the persisted row never contains the wrong state)

## Proposed approach

Using the existing realistic fixture (from 0655), call `create_portfolio_brief(conn, force=True)` with the LLM stubbed to return a deliberately wrong response — specifically `{"headline": "All good.", "what_changed": [], "key_question": "Nothing.", "portfolio_state": "STABLE"}` while `attention_items` contains a high-severity Guardian finding. Then:

1. **Read back all three tables** and assert they agree:
   - `ai_insights.insight` → `portfolio_state` = URGENT (not STABLE)
   - `portfolio_brief_snapshots` latest row → same `brief_id` and `portfolio_state`
   - `portfolio_brief_provenance` → `brief_id` matches, `briefing_output_json.portfolio_state` = URGENT

2. **Verify `source_refs_json`** points to actual seeded IDs:
   - Guardian finding → `source_refs` contains an entry with `source_type="guardian_finding"` and the seeded `finding_id` (or `(agent_type, ticker, finding_type)` key)
   - Recommendation → `source_refs` contains `source_type="recommendation"` with the seeded `rec_id`
   - News event → `source_refs` contains `source_type="news_event"` with the seeded `event_id`

3. **Verify `brief_id` integrity:** the `brief_id` returned by `create_portfolio_brief()` matches what is stored in all three tables — no mismatch scenario possible.

4. **Verify `policy_overrides`** in `briefing_output_json` records the STABLE → URGENT correction (from 0654).

Stub the LLM with a simple fixture function that returns the predetermined wrong response, injected via a mock or direct parameter.

## Touches

- `tests/test_portfolio_brief.py` (or new `tests/test_persistence_chain.py`) — new test class using the 0655 fixture + LLM stub
- No new production code changes expected; may surface bugs in `create_portfolio_brief()` or `_build_source_refs()`

## Done when

- [ ] `create_portfolio_brief()` is called with LLM returning `portfolio_state=STABLE` while a high-severity attention item exists
- [ ] `ai_insights.insight.portfolio_state` = URGENT (policy corrected before persist)
- [ ] `portfolio_brief_provenance.briefing_output_json.portfolio_state` = URGENT
- [ ] Both tables carry the same `brief_id`
- [ ] `source_refs_json` contains entries for the seeded Guardian finding, recommendation, and news event with correct `source_type` and source IDs
- [ ] `policy_overrides` in persisted output records the STABLE → URGENT correction
- [ ] No assertion reads back a stale/wrong state from any of the three tables
