# Preserve Deterministic Brief Items Through the UI

- **ID:** 0625
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0619, 0624

## Problem

The deterministic brief state creates stable item keys (`guardian:GRMN:position_risk`, `rec:1234`, `news:<event_id>`, `thesis:ANET`). Then the LLM receives those items and regenerates new objects without the stable key. The UI falls back to `attention_0`, `attention_1`, `opp_0` for response buttons, breaking the provenance chain. Worse, dismissal history grouped by `item_key` means `attention_0` from completely different briefs can collide. The LLM also risks silently omitting an important deterministic risk by not including it in its output.

Additionally, `source_refs` are currently taken from `briefing_output.get("source_refs", [])` — asking the LLM to provide provenance. That's backwards: source references should be generated deterministically from the underlying item keys.

## Proposed approach

- **LLM scope reduction:** The LLM should produce only: `headline`, `what_changed` narrative, `key_question`, and optionally a short `portfolio_state` explanation. It should not regenerate `needs_attention`, `opportunities`, or `watch`.
- **Direct pass-through:** `needs_attention`, `opportunities`, and `watch` items come directly from `brief_state`, retaining stable keys, severity, source IDs, Critic verdicts, and `is_new` flags. The UI renders these items as-is; the LLM's narrative is displayed separately above them.
- **Deterministic source_refs:** Generate `source_refs` from item keys programmatically: `rec:123` → `recommendation_id=123` → `episode_id`, `agent_run_id`, `critic_review_id`; `news:abc` → `event_id=abc` → `snapshot_hash`, article IDs; `guardian:GRMN:position_risk` → `finding_id`, `agent_run_id`. The LLM never writes provenance.
- **Stable response keys:** Because items come from brief_state directly, every ACT/DISMISS/DEFER button carries the real `item_key` (e.g. `guardian:GRMN:position_risk`), not a positional index.

## Touches

- `agents/briefing_agent.py` — narrow LLM output schema to `headline`, `what_changed`, `key_question`, `portfolio_state`; remove LLM generation of `needs_attention`/`opportunities`/`watch`/`source_refs`
- `portfolio_ai.py` — `build_portfolio_brief_state()` items pass through to UI; add deterministic `source_refs` generation
- `serve.py` — `_handle_ai_daily()` merges LLM narrative with deterministic items before returning to dashboard
- `generate_dashboard.py` — render items from deterministic section; LLM headline/narrative rendered separately
- `tests/` — assert that items in API response carry stable keys; assert LLM output does not contain needs_attention

## Done when

- [ ] `needs_attention`, `opportunities`, and `watch` in the API response come from `brief_state` directly, not from LLM output
- [ ] Every item in those sections carries its stable `item_key` (not `attention_0`, `opp_0`, etc.)
- [ ] LLM output is limited to `headline`, `what_changed`, `key_question`, `portfolio_state`
- [ ] `source_refs` are generated deterministically from item keys, not from LLM output
- [ ] ACT/DISMISS/DEFER buttons in the UI carry the real `item_key`
- [ ] No deterministic risk item can be silently dropped by LLM omission
