# Require Current-Contract Complete Production Certification

- **ID:** 0542
- **Status:** done
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

- [x] Every scoring run records its scorer contract hash.
- [x] Formal acceptance rejects old-contract and PARTIAL ledger runs.
- [x] A current-contract COMPLETE run with zero failures satisfies the ledger gate.
- [x] Production verification records the 28-holding accounting and hash results.
- [x] Formal 0535 rerun is gated on this certification.

## Progress — 2026-09-20

Implemented current-contract hash storage at run start, current-contract COMPLETE-run requirements, and rejection tests. A fresh 28-holding production cycle is running on optiplex; formal 0535 remains gated until it finishes with 28/28 and zero failures.

## Follow-up review — 2026-09-20

The current-contract predicate exists, but the formal threshold calculation does not yet require it. 0544 separates historical accounting integrity from existential current-contract certification and wires both gates into the acceptance verdict.

## Production verification — 2026-09-20

Optiplex run `51625048-8212-4e8b-892d-be9728ed881c` completed 28/28 with zero failures (20 supported companies, 8 unsupported instruments). Read-only verification confirmed exact current holdings membership, all 28 terminal run items, matching current scorer hash `7a0fe1256ab2cefdc6c0d3bd06ec1a71e73aa07bf628deeda058cd61e509447b`, matching universe hash `e3e1b392f1b02361074888d7156fd322fcd8529d6e6428783b2e1a51aad2a297`, and supported score prompt/evidence provenance. Historical integrity and full-portfolio certification both PASS. Log: `out/macro_certification_ca33690.log` on optiplex.
