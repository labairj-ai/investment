# Prospective Population Contract

- **ID:** 0419
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0418

## Problem

Opportunity Hunter currently applies an early-return gate (`top base score < 45 → return []`)
before generating the sweep cohort ID and before shadow-scoring models. This means the learner
never accumulates prospective observations for sweeps where the base strategy would not act.
Yet those same candidates enter `decision_episodes` and eventually flow into the retrospective
training corpus. The result is a population mismatch: training on all scored candidates but
prospectively validating only on days the base strategy already passed its threshold. This
makes the challenger's prospective metrics optimistically biased toward high-quality days.

## Proposed approach

- Move shadow scoring (cohort ID generation + `score_for_observe()`) to BEFORE the
  `_MIN_COMPOSITE` early-return gate in `run_opportunity_hunter()`.
- Add a boolean field `base_recommendation_eligible` to the sweep ledger (from 0418) and/or
  to `model_observations` so the two populations can be analyzed separately.
- Prospective metrics in `compute_prospective_metrics()` should be computed for:
  - all cohorts (complete picture)
  - eligible-only cohorts (apples-to-apples with live execution)
  and returned as distinct keys so both are visible.
- Update `learning_readiness_report()` to expose which population was used for prospective
  evidence.
- Alternative acceptable design: keep current early-return position but explicitly record it
  as a population restriction in the readiness report and enforce that training is filtered
  to the same eligible population.

## Touches

- `agents/opportunity_agent.py` — move shadow scoring before early-return gate
- `agents/learning/calibration.py` — `compute_prospective_metrics()` population labeling
- `agent_db.py` — optional: `base_recommendation_eligible` column on learning_sweep_runs
- `tests/test_calibration.py` — tests verifying shadow scoring occurs even when base threshold
  not met

## Done when

- [ ] Shadow scoring happens for all OH sweeps regardless of base score threshold
- [ ] `base_recommendation_eligible` is recorded per cohort (true when top base score >= 45)
- [ ] `compute_prospective_metrics()` returns separate eligible/all population metrics
- [ ] Readiness report explicitly states which population prospective evidence covers
