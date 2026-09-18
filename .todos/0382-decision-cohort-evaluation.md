# Persist Cohort ID and Base Selection for True Alpha Delta

- **ID:** 0382
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0375, 0379

## Problem

`selection_alpha_delta` currently compares the mean outcome of challenger-selected candidates against the mean outcome of base top-quintile candidates across the entire observation window — not the same decision cohort. This is not a valid counterfactual: on any given Opportunity Hunter run, the base and challenger may rank candidates differently, so the global quintile means do not isolate what changed. The correct measurement requires knowing, per run, which specific candidate the base would have selected versus which the challenger selected, and comparing their individual outcomes.

## Proposed approach

- Add `decision_cohort_id TEXT` to `model_observations` — populated from the originating Opportunity Hunter `run_id` (or a timestamp-based identifier if a formal run_id doesn't exist yet).
- Add `base_would_select INTEGER` (boolean 0/1) to `model_observations` — true when the base model alone (no challenger adjustment) would have selected this candidate in the same run.
- At score time in `score_for_observe()`, compute and record `base_would_select` using the base score ranking within the current candidate set.
- In `compute_prospective_metrics()`, compute `selection_alpha_delta` as: for each cohort where base and challenger diverge (base picks X, challenger picks Y), compute `outcome(Y) - outcome(X)`; average across divergent cohorts.
- Also track `n_divergent_cohorts` — the number of runs where base and challenger made a different selection — as the meaningful sample size for `selection_alpha_delta`.

## Touches

- `agent_db.py` — `_new_cols`: `decision_cohort_id TEXT`, `base_would_select INTEGER` on `model_observations`
- `agents/learning/challenger.py` — `score_for_observe()`: populate both new fields
- `agents/opportunity_agent.py` — pass run_id or generate cohort_id per invocation
- `agents/learning/calibration.py` — `compute_prospective_metrics()`: recompute `selection_alpha_delta` using cohort-matched pairs; add `n_divergent_cohorts`
- `tests/test_calibration.py` — test cohort-matched delta vs global quintile delta

## Done when

- [ ] `decision_cohort_id` and `base_would_select` persisted in `model_observations` at score time
- [ ] `selection_alpha_delta` computed as mean per-cohort outcome delta (challenger pick vs base pick) across divergent runs
- [ ] `n_divergent_cohorts` reported alongside `selection_alpha_delta`
- [ ] Old rows without `decision_cohort_id` gracefully excluded from cohort-delta calculation
- [ ] `python -m pytest tests/` passes with no regressions
