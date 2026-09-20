# Require Current-Contract Production Certification

- **ID:** 0544
- **Status:** done
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0542

## Problem

The ledger checker can calculate current-contract certification, but the formal acceptance verdict currently reconstructs only historical arithmetic integrity. Old-contract or PARTIAL runs can therefore satisfy the ledger gate even when no current COMPLETE production run exists.

## Proposed approach

- Keep historical accounting integrity as one gate: every relevant run reconciles expected, scored, and failed counts.
- Add a separate existential certification gate requiring at least one current-contract run with `COMPLETE`, zero failures, complete scoring, and reconciled supported/unsupported sub-accounting.
- Wire both gates into `_check_thresholds()` and the final verdict.
- Add integration tests for old-only, old-plus-current, current PARTIAL, wrong-contract COMPLETE, and sub-account mismatch cases.

## Touches

- `scripts/validate_macro_scorer.py`
- Ledger and acceptance tests

## Done when

- [x] Historical integrity and current certification are separate checks.
- [x] Acceptance requires both checks to pass.
- [x] An old valid run plus a current valid run passes.
- [x] PARTIAL, wrong-contract, and sub-account-mismatch runs block acceptance.
