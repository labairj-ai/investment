# Base Degradation Window on Cohort Count Not Row Count

- **ID:** 0401
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** none

## Problem

The active degradation monitor windows on `ORDER BY id DESC LIMIT 30` candidate rows from `model_observations`. If an Opportunity Hunter sweep contains 20 candidates, the latest 30 rows represent only one full cohort plus part of another, making `n_divergent_cohorts_in_window >= 5` practically unreachable regardless of how many PAPER_ACTIVE decisions have been made. The feature is named cohort-based degradation, but the actual unit of observation is a candidate row, so the threshold logic is misaligned with the intended semantics.

## Proposed approach

- Replace the `LIMIT 30` row query with a two-step query: first find the latest N distinct `decision_cohort_id` values, then load all candidate observations belonging to those cohort IDs.
- Choose N in the range of 20–30 complete cohorts (subject to existing mature-outcome hysteresis).
- Persist both `n_cohorts_in_window` and `n_candidate_rows_in_window` in each degradation snapshot so the window size is auditable.
- Open question: what is the right value of N, and should it be configurable or hardcoded?

## Touches

- Active degradation monitor query / windowing logic
- Degradation snapshot schema or storage (to add cohort/row count fields)
- Any threshold constants that reference the current 30-row window assumption
- Tests for degradation monitor behavior

## Done when

- [ ] `LIMIT 30` candidate-row window is replaced with a latest-N-cohorts window
- [ ] All observations for each selected cohort ID are included (not truncated mid-cohort)
- [ ] Each degradation snapshot records both cohort count and candidate-row count
- [ ] `n_divergent_cohorts_in_window` threshold is reachable under normal OH sweep sizes
- [ ] Tests verify window behavior using cohort count, not row count
