# Separate Experiment Champion from LLM Recommendation Lineage

- **ID:** 0354
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0345

## Problem

After 0345, "champion" means two different things in different code paths:

- **Recommendation/live champion**: the LLM-selected candidate, stored as `champion_ticker` in `decision_variants` and `selected` in the recommendation
- **Experiment champion**: `scored[0]`, top-1 by base composite score, no LLM, used for CHAMPION_BOOK fills

These share no explicit link. A dashboard metric like "challenger diverged from champion N% of the time" is ambiguous — it could refer to either. This will cause confusion when reviewing portfolio performance or debugging the experiment.

## Proposed approach

- Rename fields in `decision_variants` to make the distinction explicit:
  - `champion_ticker` → `recommendation_control_ticker` (the LLM-selected candidate)
  - Add `experiment_champion_ticker TEXT` (the base-score top-1, recorded at variant creation time)
  - Keep `variant_ticker` as `challenger_ticker` (or add alias)
- In `_insert_decision_variant()` in `opportunity_agent.py`: populate `experiment_champion_ticker = scored[0]["ticker"]` at recording time alongside the LLM-selected `recommendation_control_ticker`
- Update `record_virtual_fills()` call site to record which `experiment_champion_ticker` drove CHAMPION_BOOK vs which `challenger_ticker` drove CHALLENGER_BOOK
- Update divergence metrics in `serve.py` to distinguish "experiment divergence" (experiment_champion vs challenger) from "recommendation divergence" (recommendation_control vs challenger)
- Update dashboard terminology: "Champion Book" label stays; tooltip clarifies it tracks the base-score top-1, not the LLM recommendation
- Add `_new_cols` migration for `experiment_champion_ticker` and `recommendation_control_ticker` (rename handled carefully to avoid breaking existing rows)

## Touches

- `agent_db.py` — `decision_variants` CREATE TABLE + `_new_cols` for renamed/new fields
- `agents/opportunity_agent.py` — `_insert_decision_variant()` populates both fields
- `serve.py` — divergence metrics use correct field for each comparison
- `generate_dashboard.py` — tooltip/label distinguishes experiment champion from LLM recommendation
- `tests/` — assert both fields populated on variant creation

## Done when

- [ ] `decision_variants` stores `recommendation_control_ticker` (LLM-selected) and `experiment_champion_ticker` (base-score top-1) as distinct, explicitly named fields
- [ ] Neither field is ever used interchangeably in metrics or dashboard labels
- [ ] "Champion divergence" in the API/dashboard specifies which champion it refers to
- [ ] Test: after `_insert_decision_variant()`, both fields are non-null and independently queryable
- [ ] `python -m pytest tests/` passes with no regressions
