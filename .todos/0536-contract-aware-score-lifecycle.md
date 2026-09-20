# Enforce Scorer Contract on Cached Macro Scores

- **ID:** 0536
- **Status:** in-progress
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0535

## Problem

Production reuses supported-company macro scores based on age, even when the stored `scorer_contract_hash` is missing or differs from the current contract. A new acceptance can therefore be active while production still consumes a score generated under an older contract.

## Proposed approach

- Require fresh cached scores to carry the current `scorer_contract_hash` before reuse.
- Apply the same check in `_get_macro_scores_block()` and `_classify_macro_coverage()`.
- Report `stale_scorer_contract` distinctly from ordinary stale or missing scores.
- Force-refresh all supported-company scores after the next accepted contract and verify their hashes match the acceptance record.

## Touches

- `portfolio_ai.py`
- Macro coverage and health reporting
- Production score refresh procedure and tests

## Done when

- [ ] Cached scores with a missing or mismatched contract hash are never reused.
- [ ] Coverage and health distinguish stale contract scores from ordinary staleness.
- [ ] Tests cover current, missing, mismatched, and fresh-score cases.
- [ ] A post-acceptance forced refresh is verified against the active contract hash.

## Completion — 2026-09-20

Implemented in `03636aa`: cache reuse, prompt blocks, coverage, and acceptance health now fail closed on missing or mismatched scorer contracts. Forced-refresh verification remains part of the production rollout record.

## Follow-up review — 2026-09-20

The downstream prompt and coverage paths are contract-aware, but `generate_holding_macro_scores(force=False)` still reuses any score younger than seven days without comparing its stored scorer hash. 0540 adds the missing cache-reuse gate and its direct regression tests.
