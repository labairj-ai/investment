# Add Real Confidence Intervals to Decision Quality Model

- **ID:** 0080
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0070, 0071

## Problem

`decision_quality.py` uses `n ≥ 10` and `|agent_edge| ≥ 2%` as the activation threshold. A `_simple_ci_half_width()` function exists but is never called. This means a finding like "agent outperformed by 4.3%, n=11" is surfaced even if the 95% CI is −8% to +16.6% — statistically indistinguishable from zero. The model will inject misleading notes into LLM prompts. This problem is compounded by 0070 and 0071: until actual execution data is wired in, many of the "confirmed" outcomes are estimated, making premature confidence intervals doubly dangerous.

## Proposed approach

- Use `_simple_ci_half_width()` (or a bootstrap alternative) to compute the 95% CI on `agent_edge`.
- Only surface a Decision Quality note when the entire CI is on one side of zero (i.e., `lower_bound > 0` or `upper_bound < 0`).
- Expose `ci_lower`, `ci_upper`, and `std_dev` in the stats dict returned by `compute_quality_stats()` so callers can inspect the interval.
- Add a second activation guard: only enable Decision Quality injection when `actual_is_estimated = False` for ≥ 80% of the rows in the category (requires 0070/0071 to be complete first).
- Consider a bootstrap resampling approach for small n (10–30): draw with replacement 1000 times, compute edge distribution, use the 2.5th/97.5th percentiles as the CI bounds. This is more robust than the normal approximation for small samples.

## Touches

- `agents/decision_quality.py` — `get_decision_quality_note()`, `compute_quality_stats()`
- `agent_db.py` — `get_outcome_statistics_by_category()` needs to return `std_dev` or variance
- `tests/test_decision_quality.py` (new) — test that CI not crossing zero is required to surface a note

## Done when

- [ ] `get_decision_quality_note()` only returns a non-empty string when the 95% CI on `agent_edge` does not cross zero
- [ ] `compute_quality_stats()` returns `ci_lower`, `ci_upper` per category
- [ ] A note is suppressed when ≥ 20% of contributing rows have `actual_is_estimated = True`
- [ ] Test: edge of 4% with high variance returns empty string; edge of 4% with low variance returns note
