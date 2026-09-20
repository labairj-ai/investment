# Add Consolidated Learning Loop Readiness Dashboard Card

- **ID:** 0385
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0379, 0380, 0381, 0382, 0383, 0384

## Problem

There is no single place to assess the state of the learning loop. Lifecycle state, promotion gate results, data health, evidence counts, and edge metrics are spread across separate DB tables and internal function returns, with no consolidated API endpoint or dashboard view. An operator wanting to answer "is this model ready to promote, and if not, why?" must either query the DB manually or instrument multiple code paths. This is the primary question during the observation period and it should have a first-class answer.

## Proposed approach

- Add a `/api/learning/readiness` endpoint (or equivalent) that computes and returns a single structured report for the current active model (or a specified model version).
- Report fields (from the feedback review):
  - `canonical_horizon` — the configured `LEARNING_TARGET_HORIZON`
  - `eligible_episodes` — episodes old enough to have matured outcomes for this horizon
  - `mature_observations` — observations with labeled outcomes
  - `independent_cohort_days` — distinct `scored_at_date` values among mature observations
  - `base_ranking_spread`, `challenger_ranking_spread`, `incremental_ranking_spread`
  - `current_lifecycle` — TRAINED / OBSERVE / PAPER_ACTIVE / SUSPENDED
  - `promotion_gates` — dict of gate name → PASS / FAIL / NOT_EVALUABLE
  - `data_health` — dict of metric name → ok / warn / block (target-horizon-scoped)
  - `next_maturity_date` — earliest date at which the next batch of observations can have matured outcomes (based on horizon length + earliest unmatured scored_at_date)
- Surface this as a card in the existing learning/model section of the dashboard.
- The computation should reuse `compute_prospective_metrics()`, `_check_promotion_gates()`, and `compute_data_health()` rather than duplicating logic.

## Touches

- `serve.py` — new `/api/learning/readiness` route
- `agents/learning/calibration.py` — possibly a thin `learning_readiness_report()` wrapper
- Frontend dashboard component — new card in the learning/model section
- `tests/test_calibration.py` — test the readiness report assembles correctly

## Done when

- [ ] `/api/learning/readiness` returns all required fields for the current model
- [ ] `next_maturity_date` is correctly calculated from the horizon length and unmatured observations
- [ ] Dashboard card displays all fields including gate statuses and health statuses
- [ ] Promotion blockers (FAIL and NOT_EVALUABLE gates) are visually distinct from PASS
- [ ] `python -m pytest tests/` passes with no regressions
