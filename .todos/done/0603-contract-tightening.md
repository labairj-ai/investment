# Contract Tightening: Thesis Pair Validation, Prompt Types, Fresh-DB Schema

- **ID:** 0603
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0598, 0599

## Problem

Three correctness gaps. (a) `map_thesis_relevance()` validates that `component_name` is in the candidate name set, but not that `(component_type, component_name)` is a valid pair. The LLM can return `component_type="risk"` with `component_name="Revenue Growth"` where Revenue Growth was a pillar candidate — the name passes validation but the wrong field (`risk_name` instead of `pillar_name`) gets set. (b) `_thesis_map_llm()` tells the model valid component types are `pillar|risk|catalyst|trigger|none`, but the candidate payload now includes `add_condition`, `trim_condition`, and `exit_condition` types. The model may return an unexpected type and the validation block will replace it with a fallback, silently discarding the match. (c) In `portfolio_ai._init_ai_tables()`, the `ALTER TABLE news_events ADD COLUMN` statements for v2 columns appear before the `CREATE TABLE IF NOT EXISTS news_events` statement. On a fresh database these ALTERs fail silently (exceptions swallowed), then the table is created without v2 columns, and v2 persistence silently fails or produces NULL columns. This is a deployment defect that won't surface until disaster recovery or a new-host migration.

## Proposed approach

- Build a `candidate_pairs` set of `(type, name)` tuples from the candidates list. After the LLM call, validate the returned `(component_type, component_name)` pair against this set instead of validating name alone. If the pair doesn't match, fall back to the keyword result rather than applying a mis-typed component.
- For the prompt type mismatch: normalize `add_condition`, `trim_condition`, `exit_condition` candidates to type `"trigger"` before building `candidate_payload` for `_thesis_map_llm()`. This keeps the prompt clean (only `pillar|risk|catalyst|trigger|none`) while still routing the extended decision-condition types through the trigger path. Update the `_set_component_name()` dispatch to handle the extended types as before.
- For the schema ordering fix: add all v2 columns (`causal_event_key`, `pillar_health_state`, `event_trigger_state`, `event_trigger_proximity`) directly to the base `CREATE TABLE IF NOT EXISTS news_events` DDL in `_init_ai_tables()`. Keep the `ALTER TABLE` statements afterward as upgrade-only paths for existing installations. Add a fresh-empty-DB test that creates the schema from scratch via `_init_ai_tables()` and asserts all v2 columns exist.

## Touches

- `agents/news/intelligence.py` — `map_thesis_relevance()` (pair validation), `_thesis_map_llm()` prompt types, candidate normalization
- `portfolio_ai.py` — `_init_ai_tables()` base `CREATE TABLE` DDL
- `tests/test_news_intelligence.py` — pair-mismatch test; fresh-DB schema test

## Done when

- [x] LLM returning `component_type="risk"` for a pillar candidate name → pillar_name set correctly (or keyword fallback used), not risk_name
- [x] `_thesis_map_llm()` prompt and candidate list use only `pillar|risk|catalyst|trigger|none`; ADD/TRIM/EXIT conditions normalized to `trigger` before the LLM call
- [x] Base `CREATE TABLE news_events` in `_init_ai_tables()` includes all v2 columns
- [x] Fresh-empty-DB test: `_init_ai_tables()` on a new DB produces a `news_events` table with all v2 columns present
- [x] Existing-DB upgrade path (ALTER TABLE) still works without errors
