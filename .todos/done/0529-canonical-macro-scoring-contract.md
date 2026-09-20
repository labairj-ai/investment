# Unify Macro Scoring Contract for Validator and Production

- **ID:** 0529
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** none

## Problem

`validate_macro_scorer.py::_score_one_ticker()` constructs its own simplified prompt (dimension definitions + ticker only, `num_predict=800`) rather than calling the same code path as production. `generate_holding_macro_scores()` builds a materially richer request: financial and geographic evidence, measured betas, confidence levels, revenue exposure, balance-sheet data, and uses `num_predict=1600`. As a result, the acceptance process validates prompt stability of a stripped-down request, not the actual production scoring contract. An N=20 acceptance run under the current code answers "is the validation prompt stable?" instead of "is the production scoring system with production evidence stable?"

## Proposed approach

- Extract a single `_build_macro_score_request(ticker, evidence, betas)` function (or equivalent) that both `generate_holding_macro_scores()` and the validator call.
- For formal validation runs, freeze a snapshot of evidence inputs for the validation universe (8 tickers × 4 dimensions) at run start so every N=20 repeat receives byte-identical evidence; store the snapshot alongside the acceptance artifact.
- Compute and store `prompt_hash`, `evidence_hash`, and `scorer_contract_hash` in the acceptance artifact and in `macro_dimension_validation` rows.
- Fix `num_predict` mismatch: validator must use the same value as production (currently 1600).
- Add a regression test asserting that `_build_macro_score_request()` produces identical output for both the validator code path and the production code path given the same ticker/evidence fixture.

Open question: should evidence snapshots live in the DB or alongside the JSON artifact on disk?

## Touches

- `validate_macro_scorer.py` (primary — _score_one_ticker, num_predict, evidence construction)
- `portfolio_ai.py` or equivalent file containing `generate_holding_macro_scores()` (extract shared function)
- Acceptance artifact schema (add prompt_hash, evidence_hash, scorer_contract_hash fields)
- `macro_dimension_validation` table schema (add hash columns)
- Test suite (new regression test for prompt identity)

## Done when

- [x] A single shared function builds the LLM request; no inline prompt construction remains in the validator
- [x] Validator uses the same `num_predict` as production
- [x] Acceptance artifact records `prompt_hash`, `evidence_hash`, and `scorer_contract_hash`
- [x] Evidence inputs for the validation universe are frozen at run start; all N repeats use byte-identical evidence
- [x] Regression test asserts validator and production requests are identical for the same ticker/evidence fixture and fails if they diverge

## Review — 2026-09-20

Partially implemented in 4dbb0c0. The shared request builder and frozen in-memory evidence exist, but the acceptance artifact does not record prompt hashes or persist the full evidence snapshot; validation rows lack prompt/evidence hashes. The prompt-identity test calls the same helper twice rather than comparing the production and validator call paths.

## Completion — 2026-09-20

Completed remaining implementation and behavioral coverage in `tests/test_macro_contract_completion.py`. Numeric thresholds, full-N gating, frozen evidence/prompt provenance, contract invalidation, UUID run persistence, timestamp exclusion, and atomic activation are verified. Historical review notes above describe the prior implementation.
