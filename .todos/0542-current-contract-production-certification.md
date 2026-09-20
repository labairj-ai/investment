# Require Current-Contract Complete Production Certification

- **ID:** 0542
- **Status:** backlog
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0540, 0541

## Problem

The production scoring ledger does not store `scorer_contract_hash`, and formal ledger integrity currently accepts any reconciled non-STARTED run, including old-contract or PARTIAL runs. That does not prove that the current scorer completed a clean production cycle before formal acceptance.

## Proposed approach

- Add and populate `scorer_contract_hash` on `macro_scoring_runs` at run start and completion.
- Keep arithmetic integrity checks, but make formal acceptance require a current-contract `COMPLETE` run with `failed_n=0`, `expected_n=scored_n`, and `supported_scored_n + unsupported_n = scored_n`.
- Add tests for old-contract, PARTIAL, failed, and current COMPLETE runs.
- Verify the forced production refresh produces 28/28 scored, zero failed, complete sub-accounting, and current hashes before rerunning 0535.

## Touches

- `portfolio_ai.py`
- `scripts/validate_macro_scorer.py`
- Ledger migration and acceptance tests
- Optiplex production database

## Done when

- [ ] Every scoring run records its scorer contract hash.
- [ ] Formal acceptance rejects old-contract and PARTIAL ledger runs.
- [ ] A current-contract COMPLETE run with zero failures satisfies the ledger gate.
- [ ] Production verification records the 28-holding accounting and hash results.
- [ ] Formal 0535 rerun is gated on this certification.
