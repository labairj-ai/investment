# Define Canonical Dimension Eligibility Policy

- **ID:** 0541
- **Status:** backlog
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0539

## Problem

The validator marks a dimension unstable when its observed range exceeds `same_input_score_max_range`, while activation derives the persisted class from standard deviation and later allows stable or borderline classes. A range-two sequence with low standard deviation can therefore be marked unstable during validation but become formally usable after activation.

## Proposed approach

- Add one `_dimension_validation_state(row, config)` function returning `stability_class`, `eligible`, and `eligibility_reason`.
- Use it for validation artifacts, diagnostics, DB persistence, and `_accepted_dim_state()`.
- Decide explicitly whether range is diagnostic or an eligibility gate; prefer a versioned standard-deviation policy with range retained as a warning metric.
- Bump the validation policy to v1.6 and document the chosen stable/borderline eligibility rule.
- Add a regression test where range exceeds one but standard deviation is below one, proving all consumers agree.

## Touches

- `scripts/validate_macro_scorer.py`
- `portfolio_ai.py`
- `validation_config.json`
- Diagnostic and acceptance tests

## Done when

- [ ] Every ticker-dimension cell has one canonical class and eligibility result.
- [ ] Validation, activation, diagnostics, and runtime usability use that result.
- [ ] Range and standard deviation cannot produce contradictory eligibility decisions.
- [ ] Config v1.6 records the policy and preserves the v1.4/v1.5 artifacts.
- [ ] Stable, borderline, unstable, and range-vs-stdev edge cases are tested.
