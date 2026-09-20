# Tighten Formal Attribution Analyses Before Learning Use

- **ID:** 0528
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0523, 0524, 0525

## Problem

`macro_attribution.py` applies the formal usability filter correctly to the per-dim bucket analyses, but the two new analytical paths from 0501 — signed rate_interaction analysis and stress MFE/MAE — do not apply the same gate. If their output is treated as formal evidence for learning decisions, it may incorporate episodes that failed the formal usability gate. Additionally, the cohort-blocked bootstrap currently estimates a CI around the overall mean alpha, but the most actionable question is whether the contrast being tested (e.g., positive vs. negative rate_interaction alpha difference) is statistically distinguishable — the CI should wrap that contrast, not just the overall mean.

## Proposed approach

**Gate or label the new analyses:**

For `_signed_interaction_analysis()` and `_stress_mfe_mae()`: either (a) filter to episodes where the relevant dimension (`rate_sensitivity`) is formally usable — same as `_filter_by_dim_usability()` — or (b) explicitly label the section `"exploratory": true` in the output JSON so downstream consumers know not to use it as formal attribution evidence. Option (a) is correct if these will feed learning; option (b) is correct if they are purely diagnostic. Pick one and document it.

**Fix cohort-blocked bootstrap CI to wrap the contrast:**

Instead of a CI around `mean(alpha)` for all episodes, compute a CI around the alpha difference between the positive-interaction group and the negative-interaction group. Resample cohorts, compute both group means in each bootstrap sample, take the difference, and report the 95% CI of that difference. A CI that excludes zero is meaningful evidence; one that includes zero is not. This is the question the analysis is supposed to answer.

**Guard minimum cohort size for contrast CI:**

The contrast CI requires sufficient episodes in both the positive and negative groups. Add a check: if either group has fewer than 10 episodes after cohort resampling, report `"insufficient_contrast_data"` rather than a misleading CI.

## Touches

- `scripts/macro_attribution.py` — `_signed_interaction_analysis()`, `_stress_mfe_mae()`, `_cohort_bootstrap_ci()`

## Done when

- [ ] `_signed_interaction_analysis()` and `_stress_mfe_mae()` either filter to formally usable episodes or carry an explicit `"exploratory": true` label
- [ ] `_cohort_bootstrap_ci()` reports a 95% CI around the positive-vs-negative rate_interaction alpha contrast, not the overall mean
- [ ] Contrast CI reports `"insufficient_contrast_data"` when either group is too small (< 10 episodes per group)
- [ ] Output JSON clearly distinguishes formal attribution analyses from exploratory diagnostics
