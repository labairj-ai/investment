# Make Scoring Runs Crash-Safe and Accountable

- **ID:** 0547
- **Status:** in-progress
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0544

## Problem

`generate_holding_macro_scores()` writes a `STARTED` row before processing, but only updates run counts at the end. If the process or remote LLM stops mid-run, a stale row can remain `expected_n=28, scored_n=0, failed_n=0`. Reconciliation then marks it `STALE_FAILED` without reconstructing its accounting, causing historical ledger integrity to fail forever.

## Proposed approach

- Add a `macro_scoring_run_items` table with one PENDING row per run-start universe ticker.
- Commit each ticker's score, history row, and run-item terminal state in one SQLite transaction.
- On stale-run reconciliation, transition remaining PENDING items to FAILED and derive the parent counts from terminal items.
- Preserve `STALE_FAILED` as an operational failure while making `expected_n == scored_n + failed_n` true.
- Ensure stale runs can never satisfy current production certification.

## Touches

- `portfolio_ai.py` scoring ledger and stale-run reconciliation
- `scripts/validate_macro_scorer.py` ledger checks
- Crash/reconciliation tests

## Done when

- [ ] A partially processed `STARTED` run is reconstructable after interruption.
- [ ] Reconciled stale runs have complete accounting and remain non-certifiable.
- [ ] A regression test verifies `STARTED 28 → N scored + 28-N failed → STALE_FAILED`.
- [ ] Historical integrity remains PASS while current certification remains BLOCKED.
- [ ] Immediate crash, unsupported fund, commit-boundary crash, and repeated reconciliation are covered.

## Implementation verification — 2026-09-20

Per-ticker terminal states commit atomically with score and history writes. Stale reconciliation reconstructs supported, unsupported, and failed counts and preserves non-certifiable STALE_FAILED status. Production and validation share the normalized holdings universe; certification requires full-refresh scope, matching universe provenance, and expected count equal to portfolio count. Fifteen recovery/universe regression tests pass, including commit-boundary failures, immediate interruption, legacy recovery, new/sold holdings, and incremental-run rejection. Production rollout verification is pending.
