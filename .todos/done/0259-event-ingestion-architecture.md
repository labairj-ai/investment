# Fix Event Ingestion: Poll Once, Ingest Independent of Quote

- **ID:** 0259
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** none

## Problem

Three related structural defects introduced or left unresolved in 7a36ed3:

**1. Poll inside per-order loop discards events for other orders.**
`process_open_orders()` loops over each local open order and calls `broker.poll_order_events(account_id, quote=bquote)` inside the loop body. Events returned for orders other than the current iteration target are silently discarded. With two open orders A and B, a single poll returns events for both; iteration A processes only A's events and throws B's away; iteration B then gets no events from the next poll. A real broker that reports each event once will have B's event permanently lost. The 0256 acceptance criterion — "poll_order_events() is called once per process_open_orders() cycle" — is not satisfied.

**2. Quote staleness blocks broker event ingestion.**
The per-order loop checks quote freshness before calling `poll_order_events()` and `continue`s early if the quote is unavailable or stale. Broker fills already executed at the exchange are authoritative and do not require a fresh local quote. If the market-data feed fails at 10:15 but the broker filled an order at 10:14, the engine will not ingest that fill until the quote feed recovers. These two concerns must be separated: quote freshness gates _new submissions_; it must never gate ingestion of broker-reported execution state.

**3. attempt_fill() still called in process_intent().**
After `submit_order()` succeeds, `process_intent()` immediately calls `broker.attempt_fill(order, bquote)`. The 0256 acceptance criterion says "attempt_fill() is not called by the execution engine in any code path." The initial-submission code path violates this. A genuine broker adapter sends an order and later hears back what happened — it does not poll a fill from the same call stack. `process_intent()` should end when the broker ACK is persisted. All fills, including an instantaneous simulation fill, must come through `poll_order_events()` → `apply_broker_fill()`.

## Proposed approach

1. **Poll once per cycle.** In `process_open_orders()`, call `broker.poll_order_events(account_id)` once before the per-order loop (no quote argument at this level). Build an event-by-order map:
   ```python
   events = broker.poll_order_events(account_id)
   events_by_order_id: dict[str, list[BrokerOrderEvent]] = {}
   for e in events:
       key = e.local_order_id or e.broker_order_id
       events_by_order_id.setdefault(key, []).append(e)
   ```
   Then the per-order loop looks up `events_by_order_id.get(order.order_id, [])`.

2. **Decouple quote from event ingestion.** Quote retrieval for pre-fill risk checks moves to a separate, optional step that never short-circuits event processing. One reasonable structure:
   ```
   poll broker events (no quote needed)
       ↓
   ingest authoritative fill events via apply_broker_fill()
       ↓
   fetch quote (for new submission decisions / risk revalidation only)
       ↓
   evaluate remaining open orders (risk, cancellation, amendment decisions)
   ```
   If the quote is unavailable, skip quote-dependent decisions; still process events.

3. **Remove attempt_fill() from process_intent().** After `submit_order()` returns the broker ACK with `broker_order_id`, persist the ACK to the local order row and return. No fill check in the same call stack. The fill will be ingested on the next `process_open_orders()` cycle (or can be surfaced immediately if reconciliation is called synchronously after submit, but that is a separate design choice).

4. **ShadowBrokerAdapter.poll_order_events()** already simulates synchronously from local state. Adding the quote argument was an optimisation; revert it to make poll quote-free. ShadowBroker can optionally accept a quote for fill simulation internally, but the ABC signature must not require it for the event ingestion use case.

5. **Add contract test.** Assert that within a single `process_open_orders()` call, `broker.poll_order_events` is called exactly once regardless of how many open orders exist. Assert that `broker.attempt_fill` is never called from `execution_engine.py` (grep or import-level mock that raises if invoked).

## Touches

- `trade_engine/execution_engine.py` — `process_open_orders()`, `process_intent()`
- `trade_engine/broker_adapter.py` — `poll_order_events()` signature (remove quote from ABC if needed)
- `trade_engine/broker_adapter.py` / `trade_engine/shadow_broker.py` — ShadowBrokerAdapter adjustments
- `tests/test_trade_engine.py` — update fill-path tests to expect event-driven flow
- `tests/test_broker_contract.py` — poll-once and no-attempt_fill contract assertions

## Done when

- [x] `broker.poll_order_events()` is called exactly once per `process_open_orders()` invocation regardless of open-order count
- [x] Events for all open orders are processed from a single poll result; no event is silently discarded because another order was the current loop iteration
- [x] `broker.poll_order_events()` is called unconditionally — quote unavailability / staleness does not skip event ingestion
- [x] `process_intent()` does not call `attempt_fill()` at any point; it ends when the broker ACK is persisted
- [x] `attempt_fill()` is not called from `execution_engine.py` in any code path (enforced by test or grep)
- [x] All fills, including shadow-simulated instantaneous fills, enter via `apply_broker_fill()`
- [x] Contract test asserts poll count == 1 and attempt_fill call count == 0 per cycle
- [x] 520+ existing tests continue to pass

## Outcome

- `process_open_orders()` rewritten: `broker.poll_order_events(account_id)` called once before the per-order loop; events indexed by `local_order_id or broker_order_id`; each order reads `events_by_order.get(order.order_id, [])`.
- Event ingestion moved to before risk revalidation; a post-event check skips risk for orders already in terminal state (FILLED/CANCELLED/EXPIRED) with intent sync before continuing.
- `process_intent()` post-submit uses `poll_order_events(account_id, quote=bquote)` for immediate fills; `attempt_fill()` not called.
- `ShadowBrokerAdapter.poll_order_events()` now guards fill simulation behind `_shadow_quote_fresh()` freshness check so stale quote tests are preserved.
- `TestPollOnceContract` added: asserts `poll_order_events.call_count == 1` with 2 open orders.
- 536 tests pass (16 new from 0259-0262).
