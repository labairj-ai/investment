# Persist Order Reservation and client_order_id Before Broker Call

- **ID:** 0253
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0251, 0252

## Problem

The 0247 implementation generates `client_order_id` but passes it immediately to
`broker.submit_order()` without first persisting a durable local record. In
`ShadowBrokerAdapter`, the `client_order_id` is written to the DB only *after* the
broker call succeeds. The dangerous crash window is: broker accepts the order → network
response lost → process dies → on restart the local DB has no record that a submission
was attempted, so the system may submit again.

Additionally, there is no unique DB index on `client_order_id`, so the uniqueness
guarantee exists only in application logic, not at the storage layer. There is also no
`PENDING_SUBMIT` / `PENDING_ACK` order state, so a partially-acknowledged order has no
canonical representation that reconciliation can recognise and recover.

## Proposed approach

1. Add `PENDING_SUBMIT` and `PENDING_ACK` to `OrderState`. The lifecycle becomes:
   `PREPARED → PENDING_SUBMIT → PENDING_ACK → WORKING → FILLED | CANCELLED | EXPIRED`
2. In `process_intent()`, before calling `broker.submit_order()`:
   - Generate `client_order_id` deterministically from `intent_id` and `account_id`.
   - Create and INSERT a local `Order` row in `PENDING_SUBMIT` state with
     `client_order_id` already set. Commit the transaction.
3. Call `broker.submit_order()`. On success, transition to `PENDING_ACK` / `WORKING`.
   On exception, leave the row in `PENDING_SUBMIT` so reconciliation can detect and
   recover it (match by `client_order_id` against broker open orders).
4. Add a unique index `UNIQUE(account_id, client_order_id)` to `orders` via migration.
5. Update `FakeBrokerAdapter.submit_timeout` to model the accepted-but-response-lost
   scenario: the fake broker *creates an internal order record* before throwing
   `TimeoutError`, so that a subsequent `get_open_orders()` call returns the order even
   though the local submit call failed. The restart + reconciliation path should detect
   the broker order via `client_order_id` and NOT re-submit.
6. Add a test: seed intent, call `process_intent()` with a timeout-after-create fake
   broker, reset the intent to PENDING, call `process_intent()` again, assert
   `broker.submit_order` was called exactly once and `orders` contains exactly one row.

## Touches

- `trade_engine/models.py` — `OrderState` enum
- `trade_engine/execution_engine.py` — `process_intent()`
- `trade_engine/broker_adapter.py` — `ShadowBrokerAdapter.submit_order()`
- `trade_engine/shadow_broker.py` — `ShadowBroker.submit_order()`
- `agent_db.py` — unique index migration
- `tests/fake_broker.py` — `FakeBrokerAdapter.submit_timeout`
- `tests/test_trade_engine.py`, `tests/test_chaos.py`

## Done when

- [ ] Local `Order` row with `client_order_id` is committed to DB before any broker network call
- [ ] `OrderState.PENDING_SUBMIT` exists and is set before submission
- [ ] `UNIQUE(account_id, client_order_id)` index exists in `orders`
- [ ] `FakeBrokerAdapter` models accepted-but-response-lost: broker order exists, local submit raises
- [ ] Restart test: submit timeout on first call, retry → broker.submit_order called exactly once
- [ ] `initialize_trading_session()` reconciliation detects `PENDING_SUBMIT` orders and resolves them
- [ ] All existing tests pass
