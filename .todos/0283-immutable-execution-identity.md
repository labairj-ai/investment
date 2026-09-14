# Never Fabricate Fill IDs; Use Authoritative Broker Identity

- **ID:** 0283
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0278, 0273

## Problem

When a `FILLED` or `PARTIALLY_FILLED` `BrokerOrderEvent` has no `broker_fill_id`, both `process_intent()` and `process_open_orders()` generate a random UUID (`event.broker_fill_id or str(uuid.uuid4())`). Since `BrokerOrderEvent.broker_fill_id` is optional, this is a normal path, not a defensive edge case. Every replay of the same broker event generates a fresh UUID, defeating the immutable-fill-ID deduplication architecture in `apply_broker_fill()`: the database sees each replay as a distinct fill and double-debits cash and position — or triggers `OverfillError`. The deduplication invariant requires that `apply_broker_fill()` is only ever called with an ID the broker issued; fabricating one breaks that invariant silently.

## Proposed approach

- When a fill event arrives with `broker_fill_id=None`, do NOT invent a UUID.
- Instead: call `broker.get_fills_for_order(event.broker_order_id)` to retrieve authoritative `BrokerFill` objects that carry real, immutable broker-issued IDs.
- Apply each returned `BrokerFill` via `apply_broker_fill()` as normal (idempotent by `broker_fill_id`).
- If `get_fills_for_order()` raises or returns empty: raise `BrokerSettlementIndeterminate` — do not fall back to a fabricated ID.
- This applies in both `process_intent()` (initial event path) and `process_open_orders()` (ongoing event polling path).
- Tests:
  - `FILLED` event with `broker_fill_id=None` → `get_fills_for_order()` called; authoritative fills applied; no UUID written to DB.
  - Replay of the same `broker_fill_id=None` event → `FillResult.ALREADY_APPLIED`; cash/position unchanged.
  - `FILLED` event with `broker_fill_id=None` + `get_fills_for_order()` returns empty → `BrokerSettlementIndeterminate`.

## Touches

- `trade_engine/execution_engine.py` — event-to-fill path in `process_intent()` and `process_open_orders()`
- `tests/test_chaos.py` — fabricated-ID and replay deduplication tests
- `tests/fake_broker.py` — may need a mode to emit events without `broker_fill_id`

## Done when

- [x] No code path calls `apply_broker_fill()` with a locally-fabricated (UUID) fill ID
- [x] Fill event with `broker_fill_id=None` triggers `get_fills_for_order()` and applies authoritative fills
- [x] Replay of a `broker_fill_id=None` event for an already-applied fill returns `ALREADY_APPLIED`; no double-debit
- [x] Fill event with `broker_fill_id=None` + `get_fills_for_order()` empty/raises → `BrokerSettlementIndeterminate`
- [x] All existing 580 tests still pass (589 pass total)

## Outcome

Both UUID fabrication sites removed: `process_intent()` initial events loop (line ~681) and `process_open_orders()` event loop (line ~813). Replacement: when `event.broker_fill_id` is None, call `broker.get_fills_for_order(event.broker_order_id)`; raise `BrokerSettlementIndeterminate` on exception or empty return; otherwise apply each returned fill via `apply_broker_fill()`. Added `no_fill_id_events: bool = False` mode to `FakeBrokerAdapter.poll_order_events()` for testing. Added `TestImmutableFillIdentity` with 3 tests covering authoritative-ID write, replay deduplication, and empty-lookup BSI.
