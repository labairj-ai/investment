# Durable Pre-Cycle Fill Reconciliation

- **ID:** 0289
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0288, 0291

## Problem

`sync_broker_state()` (0284) correctly sequences broker event ingestion before new intent evaluation, but it relies solely on `poll_order_events()` — a transient event queue backed by WebSocket notifications for Alpaca. A temporary WebSocket disconnect or a missed push event can leave a real fill undetected until the next reconciliation sweep, during which the engine evaluates new risk decisions against stale cash and positions. The existing cursor-replay window in `get_fills()` mitigates some of this, but there is no authoritative pull-based fill sync that runs every cycle as the ground-truth complement to the push-based event queue.

## Proposed approach

- Enhance `sync_broker_state()` (or add a dedicated `sync_fills_from_ledger()` sub-step) that pulls authoritative fill records from the broker's durable activity ledger in addition to consuming push events.
- For Alpaca: use the Account Activities endpoint (`GET /v2/account/activities/FILL`) with `since = last_sync − overlap_window` — the same cursor-replay model already in `get_fills()`. Each FILL record carries `id` (execution_id), `order_id`, `qty`, `price`, `side`, `symbol`, and `transaction_time`, mapping cleanly to `BrokerFill`.
- Apply each returned fill via `apply_broker_fill()` (idempotent via `INSERT OR IGNORE`), so replayed fills are no-ops and truly new fills update cash/positions before risk evaluation.
- Keep WebSocket events as the low-latency notification path; let Account Activities be the replayable ledger that closes gaps on disconnect or missed events.
- Add a chaos test: WebSocket stream produces no events (simulate via `poll_order_events()` returning empty), but a fill exists in the activity ledger → fill is ingested in the pre-cycle sync → next intent risk decision reflects updated cash.

## Touches

- `trade_engine/execution_engine.py` — `sync_broker_state()` or new ledger-sync helper
- `trade_engine/alpaca_adapter.py` — implement Account Activities FILL polling
- `trade_engine/broker_adapter.py` — possibly add `get_account_activities(since)` to ABC, or extend `get_fills()` semantics
- `tests/test_chaos.py` — no-events-but-ledger-has-fill test

## Done when

- [ ] `sync_broker_state()` or a called sub-step pulls authoritative fills from a durable broker ledger in addition to consuming the event queue
- [ ] Activity-pulled fills are applied via `apply_broker_fill()` with idempotency (duplicate activity records are no-ops)
- [ ] A WebSocket-blackout scenario (empty `poll_order_events()`) still ingests fills present in the ledger before new intent evaluation
- [ ] Alpaca `AlpacaAdapter` implements the Account Activities FILL endpoint for `get_fills()` and/or `get_fills_for_order()`
- [ ] Chaos test covers the ledger-only path
- [ ] All existing tests still pass
