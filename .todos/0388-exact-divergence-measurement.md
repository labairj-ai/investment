# Measure Cohort Divergence by Episode Identity Not Outcome

- **ID:** 0388
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0386, 0387

## Problem

`n_divergent_cohorts` in `compute_prospective_metrics()` currently detects divergence by comparing lists of outcome alpha values (`if ch_picked != base_picked`). This produces false negatives (base picks A +4%, challenger picks B +4% → treated as same decision) and false positives (lists differ in length because base currently holds the quintile). After 0386 fixes both to top-1, the comparison is still outcome-list equality rather than identity. The right test is: did the learner actually choose a different candidate than the base strategy?

## Proposed approach

- Store `base_selected_episode_id` and `challenger_selected_episode_id` on `model_observations` (added in 0386), or at minimum ensure the selected row's `episode_id` can be retrieved.
- In `compute_prospective_metrics()`: for each cohort, divergence = `base_selected_episode_id != challenger_selected_episode_id`.
- Compute per divergent cohort: challenger outcome, base outcome, delta. Aggregate into:
  - `n_divergent_cohorts` — count of runs where picks differed
  - `challenger_wins` / `base_wins` / `ties`
  - `mean_selection_delta` and `median_selection_delta`
- Return all of these from `compute_prospective_metrics()`.
- Add these fields to `learning_readiness_report()` output.

## Touches

- `agents/learning/calibration.py` — `compute_prospective_metrics()`, `learning_readiness_report()`
- `agent_db.py` — `_new_cols` if episode ID columns are added
- `tests/test_calibration.py`

## Done when

- [ ] Divergence determined by episode identity (not outcome equality)
- [ ] `compute_prospective_metrics()` returns `n_divergent_cohorts`, `challenger_wins`, `base_wins`, `ties`, `mean_selection_delta`
- [ ] Tests cover: same-episode same-outcome (not divergent), different-episode same-outcome (divergent), different-episode different-outcome
- [ ] Full test suite passes
