# Thesis Semantic Mapper (LLM-Based)

- **ID:** 0591
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0581, 0589

## Problem

`map_thesis_relevance()` performs keyword matching against pillar/risk/catalyst names and returns a `thesis_relevance` score based on token overlap. This is a bag-of-words retrieval step, not thesis reasoning. A MARGIN event on a stock whose thesis pillar is "Expanding operating leverage" gets matched only if the word "margin" appears in the pillar text. More importantly, `trigger_proximity` currently means "a thesis pillar is already WARNING or VIOLATED" — it is a snapshot of current health, not an assessment of whether this specific event is approaching a review or exit trigger. Users see a high trigger_proximity on every stressed holding regardless of whether today's news is actually relevant to the trigger condition.

## Proposed approach

- Keep keyword matching as a fast pre-filter: retrieve 2–4 candidate thesis components (pillars, key risks, catalysts, ADD/TRIM/EXIT conditions) whose text has the most token overlap with the event's `event_type`, `summary`, and `affected_metric`.
- Pass the top candidates plus the event evidence (event_type, direction, magnitude, summary, affected_metric, horizon) to the LLM in a short focused prompt.
- Require structured JSON output: `{component_type, component_name, relationship: STRENGTHENS|WEAKENS|SUPPORTS|CONTRADICTS|NONE, relevance: 0–1, trigger_state: NONE|APPROACHING|POSSIBLE_MATCH, explanation, confidence: 0–1}`.
- The LLM is NOT permitted to declare a trigger definitively fired. `POSSIBLE_MATCH` means the event evidence is consistent with the trigger condition but the Thesis Monitor / rule engine must confirm.
- If no candidate components are retrieved by the keyword step, return `{thesis_relevance: 0, relationship: NONE}` without calling the LLM.

## Touches

- `agents/news/intelligence.py` — `map_thesis_relevance()` (new LLM call, structured output validation)
- New short prompt template for thesis mapping (separate from event extraction prompt)

## Done when

- [ ] Keyword step retrieves 2–4 candidate thesis components and passes them to LLM
- [ ] LLM returns structured JSON with `component_type`, `relationship`, `relevance`, `trigger_state`, `explanation`, `confidence`
- [ ] Unrecognized relationship or trigger_state values are rejected with fallback to NONE
- [ ] LLM cannot declare EXIT/TRIM triggers definitively fired — max is `POSSIBLE_MATCH`
- [ ] Events with no keyword-matched candidates return `thesis_relevance: 0` without calling LLM
- [ ] `trigger_proximity` reflects whether this event approaches a trigger, not current pillar health
