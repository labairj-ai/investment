# Restrict Decision Metrics to Divergent Cohorts Only

- **ID:** 0400
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** none

## Problem

`cohort_deltas.append(delta)` and the `_win_deltas` population run unconditionally, so mean selection delta, W/L/T counts, and win rate include all cohorts — even those where base and challenger selected the same episode. Same-choice cohorts contribute a delta of zero and dilute the measured effect size, making the learning signal appear weaker than it actually is. The readiness API labels this metric as "decision evidence from divergent cohorts," but the implementation does not match that label.

## Proposed approach

- In the readiness module: move `cohort_deltas.append(delta)` inside the `if challenger_episode != base_episode:` branch.
- In the degradation module: move `_win_deltas` population (and any associated win/loss/tie counting) inside the same divergence condition.
- Confirm that `n_divergent_cohorts` is still incremented in the same block so the denominator stays consistent.
- Update any readiness API field names or docstrings that claim divergent-only semantics but currently receive all-cohort data.
- Open question: should same-choice cohorts be tracked separately (e.g., `n_agreement_cohorts`) for diagnostic visibility, or simply omitted entirely?

## Touches

- Readiness module (cohort delta accumulation loop)
- Degradation module (`_win_deltas` accumulation loop)
- Readiness API response schema / field labels
- Tests asserting on mean_selection_delta, win rate, or W/L/T counts

## Done when

- [ ] `cohort_deltas` in readiness only contains deltas from cohorts where selected episodes differ
- [ ] `_win_deltas` in degradation only contains deltas from divergent cohorts
- [ ] W/L/T counts and win rate exclude same-choice cohorts in both modules
- [ ] `n_divergent_cohorts` denominator matches the restricted delta set
- [ ] Readiness API labels accurately describe divergent-only semantics
- [ ] Tests updated to reflect corrected (non-diluted) effect sizes
