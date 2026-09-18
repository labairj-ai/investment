# Add Bootstrap CI and Evidence State to Readiness Card

- **ID:** 0402
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0400

## Problem

The readiness card exposes mean selection delta and W/L/T counts but provides no uncertainty estimate, so a mean edge of +4.2% from 5 cohorts looks identical to the same mean from 40 cohorts. Without a confidence interval or evidence classification, operators cannot judge whether the learning signal is actionable or noise. The calibration module currently has no `selection_delta_ci` or median selection delta fields.

## Proposed approach

- Bootstrap divergent cohort deltas (one delta per cohort, not per candidate row) to produce a 90% CI for the mean selection edge.
- Add median selection delta alongside the existing mean.
- Derive an evidence state from the CI: POSITIVE (lower bound > 0), NEGATIVE (upper bound < 0), INCONCLUSIVE (CI straddles 0).
- Expose all three on the readiness card: mean, median, 90% CI bounds, divergent cohort count, evidence state.
- Example target output: `Mean selection edge: +3.1% | 90% CI: -0.8% to +6.7% | Divergent cohorts: 11 | Evidence: INCONCLUSIVE`
- Open question: what bootstrap sample count is appropriate given the small expected cohort counts (5–40)? 1000–5000 resamples is typical.

## Touches

- Calibration module (add bootstrap CI computation)
- Readiness report / card (add median, CI, evidence state fields)
- Readiness API response schema
- Tests for readiness report output

## Done when

- [ ] Bootstrap CI (90%) over divergent cohort deltas is computed in the calibration module
- [ ] Median selection delta is exposed alongside mean
- [ ] Evidence state (POSITIVE / INCONCLUSIVE / NEGATIVE) is derived from the CI bounds
- [ ] Readiness card displays mean, median, CI, cohort count, and evidence state
- [ ] Tests cover all three evidence state outcomes
