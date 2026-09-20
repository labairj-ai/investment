# Bind Certification to the Full Portfolio Universe

- **ID:** 0545
- **Status:** in-progress
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0544, 0548

## Problem

A current-contract COMPLETE run with one rescored holding could satisfy certification even though the acceptance is intended to establish a portfolio-wide production boundary. The first certification must prove the exact scorer processed the full current portfolio universe.

## Proposed approach

- Store run scope (`full_refresh` or `incremental`), portfolio count, and a hash of the normalized sorted ticker universe on `macro_scoring_runs`.
- Require formal certification to use `full_refresh`, the current portfolio-universe hash, and expected count equal to the canonical current holdings universe.
- Derive the validator's expected universe from the same holdings source and normalization helper used by production scoring; do not use `holding_macro_scores` as the source of truth.
- Verify all current `holding_macro_scores` payloads carry the same scorer hash; supported scores also carry prompt and evidence provenance.
- Record the 28-holding certification evidence before rerunning 0535.

## Touches

- `portfolio_ai.py` run ledger and scoring path
- `scripts/validate_macro_scorer.py` certification gate
- Ledger migrations and tests

## Done when

- [x] Full-refresh scope and portfolio-universe hash are stored for each scoring run.
- [x] Formal certification rejects incremental or wrong-universe runs.
- [ ] The 28-holding run is verified as COMPLETE with zero failures and matching hashes.
- [ ] A regression test covers a valid one-holding run being rejected for formal certification.
- [ ] New and sold holdings are reflected by certification-universe tests.
- [ ] The scorer uses one run-start universe snapshot for the entire production run.

Code is implemented; a fresh forced production refresh is still required to create the first certification row containing the new scope and universe provenance.

## Implementation verification — 2026-09-20

Per-ticker terminal states commit atomically with score and history writes. Stale reconciliation reconstructs supported, unsupported, and failed counts and preserves non-certifiable STALE_FAILED status. Production and validation share the normalized holdings universe; certification requires full-refresh scope, matching universe provenance, and expected count equal to portfolio count. Fifteen recovery/universe regression tests pass, including commit-boundary failures, immediate interruption, legacy recovery, new/sold holdings, and incremental-run rejection. Production rollout verification is pending.
