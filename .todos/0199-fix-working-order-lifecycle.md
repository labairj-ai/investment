# Fix Working Order Lifecycle: Split New-Intent vs Open-Order Processing

- **ID:** 0199
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`run_pending_intents()` only queries `WHERE status='PENDING'`. Once an intent transitions to `APPROVED` with a `WORKING` order that didn't fill (limit didn't cross the market), the scheduler never revisits it. The order stays WORKING forever. DAY expiration also never fires because `attempt_fill()` must run again to trigger it.

## Proposed approach

Split `execution_engine.py` into two entry points called by the scheduler on every cycle:

**`process_new_intents(account_id, conn)`**
- Selects `trade_intents WHERE status='PENDING'`
- Runs risk evaluation → order submission (unchanged from current `process_intent`)
- If no fill on first attempt, intent stays `APPROVED` / order stays `WORKING` — that's expected

**`process_open_orders(account_id, conn)`**
- Selects `orders WHERE state IN ('WORKING', 'PARTIALLY_FILLED') AND account_id=?`
- Fetches fresh quote for each symbol
- Calls `attempt_fill()` — fill, or remain WORKING, or expire if DAY + after market close
- On fill: update intent status → `FILLED`, write `executed_actions`
- On expiry/cancel: update intent status → `EXPIRED`/`CANCELLED`

**`run_execution_cycle(account_id, conn)`** — top-level entry (replaces `run_pending_intents`):
```python
process_new_intents(account_id, conn)
process_open_orders(account_id, conn)
```

Scheduler hook in `serve.py` calls `run_execution_cycle` instead of `run_pending_intents`.

Also: intent status must stay in sync with order terminal states (FILLED, EXPIRED, CANCELLED, REJECTED) — write a helper `_sync_intent_from_order(order, conn)`.

## Touches

- `trade_engine/execution_engine.py` — refactor into two passes
- `serve.py` — update `/api/trade-engine/run` and any scheduler hook

## Done when

- [ ] WORKING order with no fill on cycle 1 gets re-attempted on cycle 2
- [ ] DAY order placed at 3:50 PM ET → expires on the next scheduler cycle after 4:00 PM
- [ ] Intent status stays in sync: FILLED order → intent FILLED; EXPIRED order → intent EXPIRED
- [ ] `run_pending_intents()` deprecated in favor of `run_execution_cycle()`
- [ ] Tests: WORKING order retried; DAY order eventually expires; intent status mirrors order state
