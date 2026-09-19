# Macro Attribution: Medians, Dispersion, and Cohort-Blocked Intervals

- **ID:** 0501
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0496, 0498

## Problem

Once 0496 is fixed and enough mature 3m outcomes accumulate (suggest ≥60 ACCEPTED episodes), the current mean-alpha bucket analysis is not sufficient to draw conclusions. Candidates from the same Opportunity Hunter sweep share the same decision date and macro environment — they are not independent observations. Averaging them without accounting for date-cohort structure inflates apparent precision. Additionally, comparing structural 1–10 buckets rather than signed interaction values misses the most informative signal.

## Proposed approach

This todo activates only when: 0498 PASS is recorded AND ≥60 ACCEPTED episodes with 3m outcomes exist.

Additions to `scripts/macro_attribution.py`:
- Report medians and IQR alongside means (more robust for skewed alpha distributions)
- Add cohort-blocked bootstrap confidence intervals: group episodes by decision_date cohort, resample cohorts (not individual episodes) to estimate uncertainty
- Compare signed interaction buckets (`rate_interaction > 0` vs `< 0`) not only structural 1–10 scores
- MFE/MAE analysis: do high-stress episodes have larger downside MAE?
- Use the `--horizon` flag (from 0496) to run the same analysis across 1m/3m/6m and check consistency

Keep descriptive — no model fitting yet. Goal: determine whether macro variables explain meaningful out-of-sample variance before committing to a macro challenger.

## Touches

- `scripts/macro_attribution.py`

## Done when

- [ ] Cohort-blocked bootstrap intervals implemented (resample cohorts, not rows)
- [ ] Signed interaction buckets compared alongside structural score buckets
- [ ] MFE/MAE included in high-stress vs low-stress comparison
- [ ] Runs only when ≥60 ACCEPTED 3m-outcome episodes exist; otherwise reports count + wait message
- [ ] No model fitting or weight changes
