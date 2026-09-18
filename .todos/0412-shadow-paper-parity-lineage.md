# Persist Cohort ID to Decision Variants for Exact Shadow-Paper Parity

- **ID:** 0412
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0411

## Problem

The integrity audit in `check_integrity.py` tries to detect shadow-vs-paper disagreement by joining `model_observations.would_select=1` to `decision_episodes.selected=1` on the same calendar date. But `decision_episodes.selected=1` is the LLM-chosen recommendation, not the paper challenger's actual candidate. When the challenger successfully overrides the LLM, the audit fires a false BLOCK. The date-only join also cross-matches observations from multiple OH sweeps on the same day. There is no direct lineage connecting a shadow observation to its corresponding `decision_variants` row.

## Proposed approach

- Generate the sweep `cohort_id` (UUID) at the very start of `run_opportunity_hunter()`, before creating any `decision_variants` or `model_observations` rows.
- Persist that `cohort_id` onto `decision_variants` (new column `decision_cohort_id`) and any virtual-fill / paper-execution records for the same sweep.
- Rewrite `_check_shadow_paper_disagreement()` in `check_integrity.py` to join on `decision_cohort_id` and compare `model_observations.episode_id` vs `decision_variants.challenger_episode_id` (and ticker as secondary sanity check).
- Add DB migration for `decision_cohort_id` column on `decision_variants`.

## Touches

- `agents/opportunity_agent.py` — cohort_id generation timing
- `agent_db.py` — migration for `decision_variants.decision_cohort_id`
- `check_integrity.py` — rewrite `_check_shadow_paper_disagreement()`
- `tests/test_calibration.py` or new `tests/test_integrity.py`

## Done when

- [ ] `decision_variants` rows for a sweep carry the same `decision_cohort_id` as their `model_observations` rows
- [ ] `_check_shadow_paper_disagreement()` joins on `decision_cohort_id` and compares `challenger_episode_id`, not `decision_episodes.selected`
- [ ] A test injects a genuine disagreement (different episode_id in shadow vs variant) and confirms BLOCK is raised
- [ ] A test confirms a correctly-matching cohort returns ok, even when the challenger differs from the LLM selection
