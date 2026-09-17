# Wire Three-Tier Resolver into Reconciliation and Fill/Event Types

- **ID:** 0269
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0263, 0268

## Problem

`resolve_local_order_id()` was added in 0263 and is wired into `apply_broker_fill`, `apply_broker_order_event`, and the execution-engine hot paths. However, the third lookup tier (by `client_order_id`) **always evaluates to None for fills and events** because `BrokerFill` and `BrokerOrderEvent` lack a `client_order_id` field — the resolver can never use that path. Additionally, `reconciliation.py` rebuilds its own ad-hoc identity key (`o.local_order_id or o.client_order_id or o.broker_order_id`) instead of calling `resolve_local_order_id()`, which means it can silently report BROKER_MISSING for orders that could be found via a secondary identifier. The INSERT OR IGNORE import path (crash-restart) is also unverified for the reconciliation leg.

## Proposed approach

- Add `client_order_id: Optional[str] = None` to `BrokerFill` (in `broker_types.py`) and to `BrokerOrderEvent`; populate it in `FakeBrokerAdapter` and `ShadowBrokerAdapter` where the field is available.
- Refactor `reconciliation.py` to call `resolve_local_order_id()` (imported from `execution_engine`) instead of the handwritten key expression. Pass a live DB connection, same pattern as the fill path.
- Verify the INSERT OR IGNORE import edge case: if a PENDING_SUBMIT row already exists (crash-restart path), reconcile should still resolve it to WORKING via `broker_order_id` after broker lookup, not silently leave it as BROKER_MISSING.
- Add tests that submit an order via `FakeBrokerAdapter` and deliver a `BrokerFill` (and a `BrokerOrderEvent`) with only `broker_order_id` set, only `client_order_id` set, and only `local_order_id` set — asserting each correctly resolves to the right local row.

## Touches

- `trade_engine/broker_types.py` — `BrokerFill`, `BrokerOrderEvent` structs
- `trade_engine/reconciliation.py` — replace ad-hoc key with resolver call
- `trade_engine/execution_engine.py` — ensure resolver import is accessible to reconciliation
- `tests/fake_broker.py` — populate `client_order_id` on emitted fills/events
- `tests/test_trade_engine.py` or `tests/test_chaos.py` — three-tier fill/event resolution tests

## Done when

- [x] `BrokerFill` and `BrokerOrderEvent` each have a `client_order_id: Optional[str] = None` field
- [x] `reconciliation.py` uses `resolve_local_order_id()` for all order-matching logic (local import avoids circular dep)
- [x] Tests pass a fill with only `broker_order_id`, only `client_order_id`; both resolve correctly
- [x] `apply_broker_order_event` resolves by broker_order_id (cancel event test)
- [x] 558 tests pass

## Outcome

`BrokerFill` and `BrokerOrderEvent` gained `client_order_id` field. Reconciliation section 3a now builds `broker_orders_by_local` using `resolve_local_order_id()` preventing false BROKER_MISSING when broker uses different IDs. Section 3b also uses resolver for matching check. Three resolution tests: fill-by-broker_order_id, fill-by-client_order_id, event-cancel-by-broker_order_id.
