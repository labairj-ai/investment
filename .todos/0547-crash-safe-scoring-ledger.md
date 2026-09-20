# Make Scoring Runs Crash-Safe and Accountable

- **ID:** 0547
- **Status:** backlog
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0544

## Problem

`generate_holding_macro_scores()` writes a `STARTED` row before processing, but only updates run counts at the end. If the process or remote LLM stops mid-run, a stale row can remain `expected_n=28, scored_n=0, failed_n=0`. Reconciliation then marks it `STALE_FAILED` without reconstructing its accounting, causing historical ledger integrity to fail forever.

## Proposed approach

- Add per-ticker run items, or checkpoint run counts after every committed ticker result.
- On stale-run reconciliation, reconstruct processed results from `holding_macro_scores_history.run_id` and mark all remaining expected tickers failed.
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
