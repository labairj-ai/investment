# Emit Real Cycle Metrics: Fill Scorecard Accuracy for Burn-In

- **ID:** 0320
- **Status:** backlog
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** 0316

## Problem

`runner.py` writes a `cycle_runs` row after every cycle (added in 0316), but several columns will always be zero or NULL because `run_cycle()` does not emit the corresponding keys in its summary dict: `duplicate_fills_skipped`, `broker_api_errors`, `cash_delta_vs_broker`, and `position_delta_vs_broker`. These are the most operationally important fields for unattended burn-in monitoring — a silently wrong broker/local delta or undetected fill replay is exactly the class of failure that paper burn-in is meant to surface.

## Proposed approach

- **`duplicate_fills_skipped`**: `apply_broker_fill()` returns `FillResult.ALREADY_APPLIED` on replay; count those return values in `run_execution_cycle()` and include in the summary dict.
- **`broker_api_errors`**: catch and count `BrokerSettlementIndeterminate` exceptions and non-2xx responses that are handled rather than re-raised; include in summary dict.
- **`cash_delta_vs_broker`**: after the cycle, call `adapter.get_broker_account()` and subtract `trading_accounts.current_cash`; write the signed difference (positive = broker has more cash than local).
- **`position_delta_vs_broker`**: call `adapter.get_positions()`, compare qty per symbol to `position_snapshots`; store max absolute delta (or a JSON summary) — or a single scalar total-position-value delta.
- **cycle wall-clock duration**: record `started_at` before `session.initialize()` and write `duration_seconds` to `cycle_runs` (add column if needed).
- **oldest unresolved order age**: query `MIN(submitted_at)` from `orders WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')` and write to `cycle_runs`.
- Alert: log at `ERROR` level when `cash_delta_vs_broker != 0`, `position_delta_vs_broker != 0`, or `execution_state` is HALTED/ERROR.
- Open question: compute broker-vs-local deltas on every cycle (costs two extra API calls) or only when `execution_state != OK`?

## Touches

- `trade_engine/execution_engine.py` — `run_execution_cycle()`: count duplicate fill replays and broker API errors; include in returned summary dict
- `trade_engine/runner.py` — post-cycle broker reconciliation calls; write all new fields to `cycle_runs`; ERROR-level logging on divergence
- `agent_db.py` — possibly add `duration_seconds` and `oldest_unresolved_order_age_minutes` columns to `cycle_runs` via migration

## Done when

- [ ] After a cycle with at least one fill, `cycle_runs.fills_applied` is non-zero
- [ ] Replaying the same fill twice in tests results in `duplicate_fills_skipped = 1`
- [ ] After a normal cycle, `cash_delta_vs_broker` reflects the actual difference (not NULL or 0 by default)
- [ ] Any cycle row with non-zero `cash_delta_vs_broker` or `position_delta_vs_broker` produces an ERROR log line
- [ ] `cycle_runs` contains `duration_seconds` populated with wall-clock cycle time
