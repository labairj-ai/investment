# Complete Thesis Contract

- **ID:** 0599
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0591, 0597

## Problem

Three gaps: (a) `map_thesis_relevance()` passes only `pillars`, `key_risks`, and `catalysts` as candidates to the LLM semantic pass. `review_triggers` and `ADD/TRIM/EXIT` conditions are not included, which are the highest-value components for "does today's news require immediate attention?" (b) After the LLM semantic pass, `thesis_relevance`, `relationship`, `trigger_state`, and `explanation` are updated, but `pillar_name`, `risk_name`, and `catalyst_name` are NOT updated to the LLM's `component_name`/`component_type`. The dashboard can therefore display a thesis component that the LLM never actually evaluated. (c) `trigger_proximity` uses the old meaning (pillar health `WARNING`/`VIOLATED`) rather than event-specific trigger proximity from the LLM. These are different concepts and should be separate fields; mixing them means trigger_bonus in `score_event()` fires even when today's news is unrelated to the trigger.

## Proposed approach

- Add `review_triggers` and `ADD/TRIM/EXIT` conditions to the keyword pre-filter and LLM candidate set in `map_thesis_relevance()`.
- After LLM call, validate `component_name` against the candidate list. Use `component_type` and `component_name` from the LLM response as the canonical mapping: update `pillar_name`, `risk_name`, or `catalyst_name` accordingly (only the matched type's field; clear the others).
- Separate `pillar_health_state` (snapshot of current pillar status: `ON_TRACK`/`WARNING`/`VIOLATED`) from `event_trigger_proximity` (event-specific: `0.0–1.0` derived from LLM `trigger_state`). Store both on `news_events`.
- `score_event()` trigger_bonus uses only `event_trigger_proximity`, not the old pillar-health-based value.
- Dashboard Watch Next and Thesis Impact sections should use `event_trigger_state` and `pillar_health_state` separately.

## Touches

- `agents/news/intelligence.py` — `map_thesis_relevance()`, `score_event()`
- `agent_db.py` / `portfolio_ai.py` — add `pillar_health_state TEXT`, `event_trigger_state TEXT`, `event_trigger_proximity REAL` columns to `news_events`
- `tests/test_news_intelligence.py` — test canonical component update; test trigger_bonus only uses event_trigger_proximity

## Done when

- [ ] `review_triggers` and ADD/TRIM/EXIT conditions are included as LLM candidates
- [ ] After LLM call, `pillar_name`/`risk_name`/`catalyst_name` reflects the LLM's chosen component
- [ ] `pillar_health_state` and `event_trigger_proximity` are separate fields on `news_events`
- [ ] `score_event()` trigger_bonus reads `event_trigger_proximity` only
- [ ] Thesis Impact card in dashboard shows the LLM-selected component, not the keyword-selected one
