# Share Canonical Macro Response Validation

- **ID:** 0537
- **Status:** backlog
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0536

## Problem

The validator parses a ticker payload and extracts numeric scores directly, while production applies `_validate_macro_score_response()` with required dimensions, score bounds, object shape, and nonempty reasons. The validator can therefore certify responses that production would reject.

## Proposed approach

- Extract one shared response parser and schema validator for production and validation.
- Require all four dimensions, dictionary-shaped dimension values, scores in 1–10, and nonempty reasons.
- Include the response-validator implementation/version in `scorer_contract_hash`.
- Add fixtures proving malformed, incomplete, and valid responses behave identically in both paths.

## Touches

- `portfolio_ai.py`
- `scripts/validate_macro_scorer.py`
- Macro acceptance tests

## Done when

- [ ] Production and validator use the same response-validation function.
- [ ] Invalid responses cannot contribute repeatability samples.
- [ ] The response-validation contract is covered by scorer identity.
- [ ] Shared fixtures pass and fail identically in both paths.
