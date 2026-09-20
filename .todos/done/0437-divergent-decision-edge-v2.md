# Report Divergent-Only and All-Cohort Edge Separately

- **ID:** 0437
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0433

## Problem

`_summarize_row_subset()` computes `incremental_selection_edge` as the difference of mean challenger top-1 alpha vs mean base top-1 alpha across *all* cohorts — including cohorts where challenger and base picked the same episode. Unchanged decisions contribute delta=0 and dilute the metric. A single large divergent winner reports as a small all-cohort edge (+1%) when the actual edge on decisions learning changed is +10%. The two numbers answer different questions and both are needed.

## Proposed approach

Update `_summarize_row_subset()` to compute and report both:
- `all_cohort_incremental_edge`: `mean(all ch_top1_alphas) - mean(all base_top1_alphas)` (current metric, rename for clarity)
- `divergent_only_mean_edge`: mean of `(ch_out - base_out)` for divergent cohorts only
- `divergent_only_median_edge`: median of same
- `divergent_win_rate`: wins / divergent_cohorts (0 when divergent_cohorts==0)
- `divergence_rate`: divergent_cohorts / total_cohorts_with_both_winners (denominator excludes cohorts missing base_would_select)

Rename existing `incremental_selection_edge` → `all_cohort_incremental_edge` to be explicit.

Final per-stratum shape:
```
n, mean_alpha, selection_alpha_spread, ranking_spread,
divergence_rate, divergent_cohorts,
challenger_top1_mean_alpha, base_top1_mean_alpha,
all_cohort_incremental_edge,
divergent_only_mean_edge, divergent_only_median_edge,
divergent_win_rate,
wins, losses, ties
```

Update any tests that assert on `incremental_selection_edge` key name.

## Touches

- `agents/learning/calibration.py` — `_summarize_row_subset()`, possibly `learning_readiness_report()`
- `tests/test_calibration.py` — update key name assertions; add tests for divergent_only_mean_edge and divergent_win_rate

## Done when

- [ ] `all_cohort_incremental_edge` and `divergent_only_mean_edge` are both present in stratified output
- [ ] `divergent_only_median_edge` and `divergent_win_rate` present
- [ ] Correctly handles zero divergent cohorts (no division by zero)
- [ ] Old `incremental_selection_edge` key removed or aliased
- [ ] Tests verify divergent-only edge differs from all-cohort edge when some cohorts are unchanged
