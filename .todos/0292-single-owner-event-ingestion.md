# Single-Owner Event Ingestion and One Submission Per Cycle

- **ID:** 0292
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** high
- **Depends:** 0289

## Problem

`process_intent()` calls `broker.poll_order_events()` after submitting a new order and silently discards events whose resolved order ID doesn't match the newly submitted order. Those events are consumed from the broker's queue and never re-delivered, so a fill for an existing WORKING order can be permanently lost in the window between the cycle's `sync_broker_state()` call and the next cycle. Additionally, `process_new_intents()` can submit multiple orders per cycle, meaning broker truth is not re-established between submissions, and pending intents are fetched with no deterministic ordering.

## Proposed approach

- Remove `broker.poll_order_events()` from `process_intent()` entirely. Only `sync_broker_state()` should drain the broker event queue; it runs at the top of every cycle before any risk evaluation or submission.
- Enforce `max_new_orders_per_cycle=1` in `process_new_intents()`: submit at most one new order per cycle and return immediately after. The next full cycle (with its leading `sync_broker_state()` ledger pull and event drain) re-establishes broker truth before authorizing another submission.
- Add explicit `ORDER BY` to the pending-intents query in `process_new_intents()` so intent priority is deterministic (e.g. `ORDER BY created_at ASC` or a priority column) rather than dependent on unordered SQL results.
- Add a chaos test: two PENDING intents + a WORKING order whose fill event arrives during the second intent's submit window → verify the fill is not lost (ingested by the next cycle's `sync_broker_state()`).

Open question: should the one-order-per-cycle limit be a hardcoded constant or a policy field? Starting as a constant is simpler and can be promoted to policy later.

## Touches

- `trade_engine/execution_engine.py` — `process_intent()`, `process_new_intents()`
- `tests/test_chaos.py` — new multi-intent event-loss test
- `tests/test_trade_engine.py` — verify ordering and one-submission-per-cycle behavior

## Done when

- [x] `process_intent()` does not call `broker.poll_order_events()`
- [x] `process_new_intents()` submits at most one new order per cycle
- [x] Pending intents are fetched with explicit `ORDER BY` (deterministic priority)
- [x] Chaos test: fill event for WORKING order B arrives during process_intent(A) → fill not lost, ingested by next cycle
- [x] All existing tests pass

## Outcome

Removed the `broker.poll_order_events()` block from `process_intent()`'s WORKING ACK path entirely. WORKING ACK now returns immediately with `fill=None`. Added `ORDER BY created_at ASC LIMIT 1` to `process_new_intents()`. Updated affected tests (test_approved_intent_creates_fill, test_fill_written_to_executed_actions, test_fills_on_submission_counted, etc.) to use `process_open_orders()` for fills. Added `TestSingleOwnerEventIngestion` in test_chaos.py with 3 tests.
