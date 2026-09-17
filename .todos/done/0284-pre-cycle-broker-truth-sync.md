# Sync Broker Truth Before New Intent Evaluation

- **ID:** 0284
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** none

## Problem

`run_execution_cycle()` calls `process_new_intents()` before `process_open_orders()`. With a real asynchronous broker, fills that arrive between cycles leave local cash and positions stale at the moment new risk decisions are made. For example: an AAPL fill arrives between cycles; cycle 2 evaluates and submits a MSFT order using the stale cash balance, then only afterwards does `process_open_orders()` ingest the AAPL fill and update cash. The MSFT risk decision was made against incorrect economic state. In shadow mode this is largely invisible because state transitions are synchronous, but it is a structural flaw that affects every real async fill.

## Proposed approach

- Extract broker event/fill ingestion out of `process_open_orders()` into a dedicated `sync_broker_state()` step.
- Call `sync_broker_state()` as the first substantive action inside `run_execution_cycle()` — before `_refresh_market_prices()`, before `process_new_intents()`, before any risk evaluation.
- `sync_broker_state()` polls `broker.poll_order_events()`, ingests all FILLED/PARTIALLY_FILLED/CANCELLED/EXPIRED events via the existing `apply_broker_fill()` / `apply_broker_order_event()` paths, and returns a result indicating success or failure.
- If `sync_broker_state()` raises or returns a blocking result, `run_execution_cycle()` returns `HALTED` before evaluating any new intents — stale economic state must never reach the risk engine.
- `process_open_orders()` retains responsibility for risk revalidation, expiry management, and order management on still-open positions, but no longer owns the initial event ingestion pass.
- The correct cycle order becomes: broker truth sync → ingest fills/events → reconcile economic state → refresh marks/NAV → evaluate new intents → submit new orders → manage remaining open orders.
- Add chaos tests: fill arrives between cycles → next cycle evaluates new intent against updated (not stale) cash/positions.

## Touches

- `trade_engine/execution_engine.py` — `run_execution_cycle()`, `process_open_orders()`; new `sync_broker_state()` function
- `tests/test_chaos.py` — inter-cycle fill ordering tests
- `tests/fake_broker.py` — may need a mode that stages fills between cycle calls

## Done when

- [x] `run_execution_cycle()` calls a broker-sync step before `process_new_intents()`
- [x] Fills arriving between cycles are ingested before any new risk evaluation in the same cycle
- [x] If the broker sync step raises or cannot establish trustworthy state, cycle returns `HALTED` before any new intent is processed
- [x] `process_open_orders()` no longer owns the initial event ingestion pass (refactored out)
- [x] Chaos test: fill ingested between cycles → new intent risk decision uses updated cash/positions
- [x] All existing 589 tests still pass

## Outcome

`sync_broker_state()` added to `trade_engine/execution_engine.py`. Called as step 1 in `run_execution_cycle()` before MtM refresh and `process_new_intents()`. Raises `BrokerSettlementIndeterminate` (→ HALTED SETTLEMENT_INDETERMINATE) on unresolvable events (ties into 0285). New `fills_on_sync` telemetry key added; `total_fills` updated to include sync fills. `ShadowBrokerAdapter.get_order()` fixed to look up by `broker_order_id` OR `order_id` (latent bug exposed by 0285 guard). 4 chaos tests added in `TestPreCycleBrokerSync`.
