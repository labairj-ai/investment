# Fix Cancel/Fill Race: Include CANCEL_REQUESTED in Event Ingestion

- **ID:** 0266
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0263

## Problem

`process_open_orders()` loads only `WORKING` and `PARTIALLY_FILLED` orders. `CANCEL_REQUESTED` orders are excluded from the per-order loop, so any fill event the broker reports for a cancel-requested order is received by `poll_order_events()` but never routed through the fill pipeline — it is silently dropped. The valid transition `CANCEL_REQUESTED → FILLED` (fill beat the cancel at the exchange) is therefore structurally unreachable. Additionally, `TestCancelFillRace` currently sets order state via direct SQL mutation rather than using real `BrokerOrderEvent` objects, so it does not exercise the actual event dispatch path.

## Proposed approach

1. Add `CANCEL_REQUESTED` to the open-order state filter in `process_open_orders()`:
   ```python
   state IN ('WORKING', 'PARTIALLY_FILLED', 'CANCEL_REQUESTED')
   ```
2. Verify that fill events for `CANCEL_REQUESTED` orders flow through `apply_broker_fill()` and produce the correct `FILLED` terminal state. The `CANCEL_REQUESTED → FILLED` transition should already be permitted by the order state machine; confirm and add it if missing.
3. Verify that a `CANCELLED` event arriving after a `FILLED` event for the same order is a no-op (`apply_broker_order_event()` logs warning and returns without mutation when order is already `FILLED`).
4. Rewrite `TestCancelFillRace` to test both orderings with real `BrokerOrderEvent` objects:
   - **Ordering A**: `FILLED` event → `CANCELLED` event. Assert final state `FILLED`, cash debited once, position incremented once.
   - **Ordering B**: local order set to `CANCEL_REQUESTED`, `CANCELLED` event arrives, then late `FILLED` event arrives. Assert final state `FILLED`, cash debited once, position incremented once.
5. Both test orderings must verify the full economic state (order state, intent status, cash, position qty).

## Touches

- `trade_engine/execution_engine.py` — `process_open_orders()` state filter; `apply_broker_order_event()` CANCEL_REQUESTED→FILLED guard
- `trade_engine/models.py` — confirm or add `CANCEL_REQUESTED → FILLED` in `_VALID_TRANSITIONS`
- `tests/test_chaos.py` — `TestCancelFillRace` rewrite (both orderings, real events)
- `tests/test_trade_engine.py` — additional state-machine assertions for cancel/fill transitions

## Done when

- [ ] `process_open_orders()` includes `CANCEL_REQUESTED` in the open-order state query
- [ ] A `FILLED` broker event for a `CANCEL_REQUESTED` order is ingested through `apply_broker_fill()` and produces `FILLED` final state
- [ ] A `CANCELLED` event arriving after `FILLED` is a no-op (no state regression)
- [ ] `TestCancelFillRace` ordering A (FILLED → CANCELLED): final state `FILLED`, cash debited once, position correct
- [ ] `TestCancelFillRace` ordering B (CANCEL_REQUESTED → CANCELLED → late FILLED): final state `FILLED`, cash debited once, position correct
- [ ] Tests use real `BrokerOrderEvent` objects, not direct SQL state mutation
- [ ] 536+ existing tests continue to pass
