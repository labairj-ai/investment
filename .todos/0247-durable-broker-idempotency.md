# Durable Broker Idempotency via Client Order ID

- **ID:** 0247
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0243, 0244

## Problem

There is no durable idempotency key generated before network submission. The dangerous crash scenario is: broker accepts the trade → network response is lost → process crashes → machine restarts. On reconnect, `initialize_trading_session()` has no way to know the order was already submitted, so it may submit again. The current contract's "same intent_id returns same ShadowBroker order" does not prove this case because ShadowBroker never sends to a real broker.

## Proposed approach

1. Generate a `client_order_id` (e.g., `intent_id` prefixed with account, or a deterministic UUID derived from intent_id) *before* any network call.
2. Store `client_order_id` durably in the `orders` table (new column) before calling `broker.submit_order()`.
3. Add `client_order_id: Optional[str]` to `BrokerAdapter.submit_order()` signature; adapters must pass it to the broker where supported.
4. In `initialize_trading_session()` / reconciliation: when scanning broker open orders, match by `client_order_id` (or `local_order_id`) to detect orders already submitted. If found, update local state instead of re-submitting.
5. Add a crash-after-submit test: write local order row with `client_order_id`, call submit, simulate network loss (mock raises), restart, verify reconciliation detects the broker order via `client_order_id` and does not re-submit.

## Touches

- `trade_engine/models.py` — `Order` gets `client_order_id` field
- `trade_engine/broker_adapter.py` — `submit_order()` signature update
- `trade_engine/broker_types.py` — `BrokerOrder.client_order_id`
- `trade_engine/execution_engine.py`
- `agent_db.py` — new column `orders.client_order_id`
- `tests/test_trade_engine.py`, `tests/test_broker_contract.py`

## Done when

- [ ] `client_order_id` is written to `orders` table before any broker submission attempt
- [ ] `BrokerAdapter.submit_order()` accepts and forwards `client_order_id`
- [ ] Reconciliation matches broker orders by `client_order_id` when `local_order_id` is missing
- [ ] Crash-after-submit test confirms no duplicate order is generated on restart
- [ ] Contract test: submit with same `client_order_id` twice → single broker order
