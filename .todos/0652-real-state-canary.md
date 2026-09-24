# End-to-End Real-State Canary

- **ID:** 0652
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0648, 0649, 0650, 0651

## Problem

All current brief tests use synthetic or minimal state. The full production path — Guardian run → producer agents → Critic → news snapshot → thesis scores → `build_portfolio_brief_state()` → `_apply_brief_policy()` → persisted provenance → `/api/brief/respond` → decision episode — has never been validated end to end against realistic DB state. Silent degradation or provenance mismatches that require realistic combinations of subsystem state are not caught by any current test.

This todo is deliberately the last in the hardening sequence. Its purpose is to validate the architecture against actual state, not to add more structural hardening.

## Proposed approach

Seed a canary DB fixture containing all of the following, each chosen to exercise a specific path:

- **Guardian**: one current (recent) finding, one old/failed run — tests freshness REQUIRED source + deduplication
- **News**: one ACTIVE event, one FADING event, one RESOLVED event — tests `get_current_news_intelligence()` recency filter
- **Trade intents**: one PENDING, one FILLED, one REJECTED — tests execution_state lifecycle in briefing prompt
- **Recommendation episode**: one existing episode with Critic verdict APPROVED — tests `open_decisions` in brief_state and ACT → episode link
- **Macro**: one stale macro score with production influence = 0 — tests ADVISORY/EXPERIMENTAL tier behavior from 0651
- **Learning**: one completed learning sweep — tests learning_state in capability summary

Generate a brief from this fixture. Then verify **manually** and with assertions:

1. `brief_state` reflects each seeded item accurately
2. `portfolio_state` satisfies the severity floor from 0650
3. `headline` and `key_question` are internally consistent with `portfolio_state`
4. `policy_overrides` is accurate (empty if LLM was already correct; populated if it was overridden)
5. `portfolio_brief_provenance` row exists and matches the generated `brief_id`
6. `source_refs` correctly trace each attention/opportunity item to its DB row
7. POST /api/brief/respond with `action=ACT` on the rec item creates a `decision_episodes` or `portfolio_brief_episodes` row referencing `brief_id` and `item_key`
8. POST /api/brief/respond with invalid `brief_id` → 400/404
9. The FADING news event does not appear in `attention_items`; ACTIVE does
10. The stale macro score does not degrade `brief_health` (verifies 0651 tier)

This test should be in a dedicated file (e.g. `tests/test_canary_real_state.py`) clearly marked as a canary/integration test.

## Touches

- `tests/test_canary_real_state.py` — new file; full fixture setup + assertions for all 10 points above
- `portfolio_ai.py` — may surface edge cases in `build_portfolio_brief_state()` or `_apply_brief_policy()` not covered by unit tests
- `serve.py` — may surface edge cases in `_handle_brief_respond()`

## Done when

- [ ] Canary fixture seeds all six state categories listed above
- [ ] `brief_state` reflects each seeded item accurately (manual verification + assertions)
- [ ] `portfolio_state` satisfies severity floor from 0650
- [ ] `headline` is internally consistent with `portfolio_state` (no STABLE headline with ATTENTION state)
- [ ] `policy_overrides` accurately reflects what the policy changed (or is empty if LLM was already correct)
- [ ] `portfolio_brief_provenance` row exists and `brief_id` matches the displayed brief
- [ ] `source_refs` trace each item to its source DB row
- [ ] ACT response creates an episode row referencing `brief_id` + `item_key`
- [ ] Invalid `brief_id` POST → 400/404
- [ ] Stale observe-only macro does not degrade `brief_health` (verifies 0651)
- [ ] FADING news not in attention_items; ACTIVE news is
