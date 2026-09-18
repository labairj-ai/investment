# Add Base-vs-Challenger Decision Edge to Stratified Metrics

- **ID:** 0433
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0427

## Problem

`_summarize_row_subset()` reports row count, mean alpha, challenger selection spread, and ranking spread — but not the metric that matters most for evaluating the challenger: within each population stratum (base-eligible vs ineligible), how often does the challenger pick a different stock than the base, and does that divergent pick outperform? Without divergence count and per-decision edge, the stratified report cannot answer whether the challenger is actually improving the base strategy.

## Proposed approach

Extend `_summarize_row_subset()` (or add a new `_summarize_decision_edge()` helper) to compute per-stratum:
- `divergent_cohorts`: cohorts where `challenger would_select=1` episode differs from `base_would_select=1` episode
- `challenger_top1_mean_alpha`: mean `outcome_alpha_90d` for `would_select=1` rows
- `base_top1_mean_alpha`: mean `outcome_alpha_90d` for `base_would_select=1` rows
- `incremental_selection_edge`: challenger_top1_mean_alpha − base_top1_mean_alpha
- `win_loss_tie`: counts where challenger outperformed / underperformed / tied base on that cohort's top-1

Target readiness report shape (per stratum):
```
cohorts: N
divergent_cohorts: N
base_top1_mean_alpha: +X.X%
challenger_top1_mean_alpha: +X.X%
incremental_selection_edge: +X.X%
win / loss / tie: N / N / N
```

## Touches

- `agents/learning/calibration.py` — `_summarize_row_subset()` or new helper, `_build_stratified_metrics()`
- `tests/test_calibration.py` — tests asserting new fields present and correctly computed

## Done when

- [ ] Stratified metrics include `divergent_cohorts`, `base_top1_mean_alpha`, `challenger_top1_mean_alpha`, `incremental_selection_edge`, and W/L/T counts per stratum
- [ ] `learning_readiness_report()` surfaces these fields
- [ ] Tests verify correct values when challenger picks differ from base picks
- [ ] Handles edge cases: no divergent cohorts, missing `base_would_select`
