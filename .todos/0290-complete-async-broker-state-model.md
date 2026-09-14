# Complete Asynchronous Broker State Model

- **ID:** 0290
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0288

## Problem

The normalized `BrokerOrderEvent` model currently handles `FILLED`, `PARTIALLY_FILLED`, `CANCELLED`, and `EXPIRED`. Alpaca's `trade_updates` WebSocket stream also emits `new`, `accepted`, `pending_new`, `rejected`, `canceled`, and `expired` lifecycle events. The normalized engine does not have a `REJECTED` branch: `sync_broker_state()` logs unknown normalized event types and continues, meaning an asynchronous `REJECTED` from Alpaca passes through as a warning instead of terminating the order's local state. More broadly, a truly unknown normalized event type — one that no adapter was supposed to emit — should fail closed as an adapter contract violation rather than silently continue.

## Proposed approach

- Add `REJECTED` to the normalized event type set (alongside `FILLED`, `PARTIALLY_FILLED`, `CANCELLED`, `EXPIRED`).
- In `sync_broker_state()` and `process_open_orders()`: handle `REJECTED` explicitly — transition the local order to `REJECTED`, update intent state, and do not count as a blocking discrepancy (it's a valid terminal state).
- Define a complete mapping from Alpaca native event types to normalized events: `new`/`accepted`/`pending_new` → informational (no state change needed); `fill`/`partial_fill` → `FILLED`/`PARTIALLY_FILLED`; `canceled`/`expired` → `CANCELLED`/`EXPIRED`; `rejected` → `REJECTED`.
- Unknown normalized event types (adapter emitted something outside the defined set) must raise `BrokerStateIntegrityError` (0288) rather than warn-and-continue — this is an adapter contract violation.
- Unknown native event types on the Alpaca side may be logged as informational and safely ignored if they don't affect order state (e.g. `pending_new`).
- Update `ShadowBrokerAdapter` and `FakeBrokerAdapter` to support emitting `REJECTED` events.
- Tests: `REJECTED` event transitions order to REJECTED + intent updated; unknown normalized event type → `BrokerStateIntegrityError`; complete Alpaca native→normalized mapping table tested.

## Touches

- `trade_engine/broker_types.py` — add `REJECTED` to normalized event enum
- `trade_engine/execution_engine.py` — `sync_broker_state()`, `process_open_orders()` REJECTED branch
- `trade_engine/alpaca_adapter.py` — native→normalized event mapping
- `tests/fake_broker.py` — REJECTED event emission support
- `tests/test_chaos.py` or `tests/test_trade_engine.py` — REJECTED path tests, unknown-normalized halt test

## Outcome

`REJECTED` added as a recognized normalized event type. `apply_broker_order_event()` handles REJECTED (valid from WORKING/PENDING_SUBMIT/PARTIALLY_FILLED) and its final `else` now raises `BrokerStateIntegrityError` instead of logging. `sync_broker_state()` and `process_open_orders()` both route REJECTED through `apply_broker_order_event()` and their `else` branches raise `BrokerStateIntegrityError` — unknown normalized event types are now an adapter contract violation. `_ALPACA_NATIVE_TO_NORMALIZED` constant added to `alpaca_adapter.py` mapping all documented `trade_updates` event types (fill/partial_fill/canceled/expired/rejected → normalized; new/accepted/pending_new/etc. → None/informational). `FakeBrokerAdapter` gains `rejected_events=True` (replaces fill events with REJECTED) and `unknown_event_type=True` (injects a BAZINGA event). 5 new tests in `TestAsyncBrokerStateModel`: REJECTED transitions order/intent via process_open_orders; unknown event raises BSI directly; unknown event halts cycle; Alpaca mapping table validated. Suite: 619 passed, 1 skipped. Next: 0291 (Alpaca URL allowlist) unblocks 0289.

## Done when

- [x] `REJECTED` is a recognized normalized event type and handled in `sync_broker_state()` and `process_open_orders()` (order → REJECTED, intent updated)
- [x] Unknown normalized event types raise `BrokerStateIntegrityError` (not warn-and-continue)
- [x] Alpaca adapter maps all documented native `trade_updates` event types to normalized equivalents or marks them informational
- [x] `ShadowBrokerAdapter` / `FakeBrokerAdapter` can emit `REJECTED` events
- [x] Tests cover REJECTED state transition and the unknown-normalized halt path
- [x] All existing 614 tests still pass (619 now, +5 new)
