# Halt New Submissions When FILLED ACK Has No Authoritative Fill Economics

- **ID:** 0278
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0273, 0271

## Problem

When a broker responds with a FILLED ACK, `process_intent()` calls `get_fills_for_order()` to retrieve authoritative fill data. If that call raises an exception, the exception propagates into `process_new_intents()`, which catches all ordinary exceptions, logs them, and continues submitting later intents. This leaves the account in a dangerous state: the broker has filled Order A, but locally the order is WORKING with stale cash and position — and risk evaluation for Order B runs against that wrong account state. Even the empty-list case (where `get_fills_for_order()` returns no fills) currently returns normally and leaves the order WORKING, with no halt. Additionally, the explicit `_update_intent_status(...FILLED)` call in the FILLED ACK path can prematurely mark an intent as FILLED if the broker's fill endpoint is temporarily lagging and returns only a subset of fills.

## Proposed approach

- Introduce a `BrokerSettlementIndeterminate` exception in `broker_types.py` (or `execution_engine.py`).
- In the FILLED ACK branch of `process_intent()`: if `get_fills_for_order()` raises or returns an empty list, raise `BrokerSettlementIndeterminate` instead of continuing. The caller (`process_new_intents()`) must treat this as a halt signal for new submissions — no further intents should be processed for the account during that cycle. Existing open-order polling and fill reconciliation may continue.
- Remove the explicit `_update_intent_status(intent_id, IntentStatus.FILLED, ...)` call from the FILLED ACK path entirely. `apply_broker_fill()` already knows whether aggregate fill quantity reaches the order quantity and drives the transition to FILLED; the explicit call can set FILLED prematurely when a lagging fill endpoint returns fewer fills than the actual fill count.
- Add tests: FILLED ACK + get_fills_for_order raises → BrokerSettlementIndeterminate raised, no subsequent intents processed; FILLED ACK + empty fill list → same; FILLED ACK + partial fill list → intent stays WORKING, not FILLED; FILLED ACK + complete fill list → intent transitions to FILLED via apply_broker_fill().

## Touches

- `trade_engine/broker_types.py` — add `BrokerSettlementIndeterminate`
- `trade_engine/execution_engine.py` — FILLED ACK path in `process_intent()`; `process_new_intents()` halt handling
- `tests/test_chaos.py` or `tests/test_trade_engine.py` — settlement-indeterminate tests

## Done when

- [ ] `BrokerSettlementIndeterminate` exception defined
- [ ] FILLED ACK + `get_fills_for_order()` raises → `BrokerSettlementIndeterminate`; no subsequent intents submitted in that cycle
- [ ] FILLED ACK + empty fill list → `BrokerSettlementIndeterminate`; no subsequent intents submitted
- [ ] Explicit `_update_intent_status(...FILLED)` removed from FILLED ACK path; aggregate `apply_broker_fill()` state owns completion
- [ ] FILLED ACK + partial fill list (n fills < full qty) → intent stays WORKING/PARTIALLY_FILLED, not FILLED
- [ ] All existing 566 tests still pass
