# Add Ranking-vs-Decision Evidence Split to Readiness Report

- **ID:** 0392
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0388, 0390

## Problem

The current `/api/learning/readiness` endpoint conflates two distinct types of prospective evidence: ranking improvement (does the model's ordering of all candidates look better than base across many observations?) and decision improvement (when the model actually changed the top candidate, did that change produce better outcomes?). These answer different questions, accumulate at different rates, and have different implications for promotion. Mixing them in a single `incremental_ranking_spread` metric obscures whether the learner is helping or merely rearranging things acceptably.

## Proposed approach

Surface both dimensions explicitly in `/api/learning/readiness` and in the dashboard readiness card:

**Ranking evidence** (uses all mature observations):
- `total_mature_cohorts` — observations with outcomes
- `incremental_ranking_spread` — challenger quintile spread minus base quintile spread
- `independent_cohort_days` — market-day diversity

**Decision-change evidence** (uses only divergent cohorts, requires 0386/0388):
- `n_divergent_cohorts` — cohorts where challenger and base chose different candidates
- `mean_selection_delta` — average (challenger outcome - base outcome) over divergent cohorts
- `challenger_win_rate` — fraction of divergent cohorts where challenger outcome > base outcome
- `challenger_wins` / `base_wins` / `ties`
- Confidence interval around `mean_selection_delta` (bootstrap or normal approx)

Update `learning_readiness_report()` to return these fields. Update the dashboard JS card to display both sections clearly.

## Touches

- `agents/learning/calibration.py` — `learning_readiness_report()`, `compute_prospective_metrics()`
- `generate_dashboard.py` — readiness card JS render
- `tests/test_calibration.py` — `TestLearningReadinessReport0385`

## Done when

- [ ] `/api/learning/readiness` returns both ranking-evidence and decision-evidence sections with the fields listed above
- [ ] Dashboard card displays ranking section and decision section separately
- [ ] Decision section is only shown when `n_divergent_cohorts >= minimum_divergent_cohorts`
- [ ] Tests cover both sections; decision section test uses multiple cohorts with known divergence/outcomes
- [ ] Full test suite passes
