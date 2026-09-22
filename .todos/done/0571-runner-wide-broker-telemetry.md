# Aggregate Broker Observation Counters Across Full Runner Invocation

- **ID:** 0571
- **Status:** done
- **Created:** 2026-09-22
- **Priority:** normal
- **Depends:** 0568

## Problem

The broker observation counters written to `cycle_runs` (`broker_fills_observed`, `broker_fills_new`, `broker_fills_duplicate`, `external_fills_observed`) are computed only inside `sync_broker_state()` during the `run_cycle()` ledger pull. Fills fetched and applied during `initialize_trading_session()` are not counted. A new external fill arriving overnight is APPLIED_EXTERNAL during `initialize()`, then ALREADY_APPLIED during the subsequent ledger pull — so the stored row shows `broker_fills_duplicate=1, external_fills_observed=0` even though this runner invocation was the one that discovered and applied the fill. The counters misrepresent what actually happened during the invocation.

Additionally, `reconciled_at` on the fills row is not updated when a fill is observed again after initial insertion; the early-dedup return path exits without touching it. `first_seen_at` is correctly immutable, but `reconciled_at` should advance on every successful broker observation.

## Proposed approach

- Lift the broker-activity accumulators out of `sync_broker_state()` and into the `runner.py` invocation scope.
- Collect the set of broker fill IDs seen during `initialize_trading_session()` and during `run_cycle()`, merge them, and deduplicate by `broker_fill_id` before computing the four counters.
- Counter definitions:
  - `broker_fills_observed` — unique broker fill IDs seen during the invocation
  - `broker_fills_new` — unique IDs that were newly inserted (INSERT succeeded)
  - `broker_fills_duplicate` — IDs that were already present when observed
  - `external_fills_observed` — observed IDs whose persisted `fills.origin != 'ENGINE'` (query the DB after the merge, not based on the return value from `apply_broker_fill()`)
- In the early-dedup path of `apply_broker_fill()`, issue an UPDATE to advance `reconciled_at` before returning ALREADY_APPLIED.
- Do not change `fills_applied` semantics — it remains engine-pipeline only.

## Touches

- `trade_engine/runner.py` — accumulate broker activity across initialize + cycle; pass merged stats to `_write_cycle_run()`
- `trade_engine/execution_engine.py` — return per-fill broker_fill_id from apply paths; update `reconciled_at` in early-dedup path
- `agent_db.py` — no schema changes expected; verify `reconciled_at` column exists (added in 0568)
- `tests/test_trade_engine.py` — add test: fill applied in initialize() appears in broker stats; external fill correctly counted even when duplicate in ledger pull

## Done when

- [ ] A fill applied during `initialize_trading_session()` contributes to `broker_fills_observed` and (if external) `external_fills_observed` in the written `cycle_runs` row
- [ ] A fill that is ALREADY_APPLIED during the ledger pull after being applied in `initialize()` is counted in `broker_fills_duplicate`, not re-counted in `broker_fills_new`
- [ ] `reconciled_at` is updated on every successful broker observation, including the ALREADY_APPLIED path
- [ ] `first_seen_at` remains immutable (set only on first INSERT)
- [ ] No existing tests regress
