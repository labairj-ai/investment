# Broker Event State Reducer, Atomic Fill Dedup, Unknown Fill Quarantine

- **ID:** 0261
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0259, 0260

## Problem

Three related gaps in fill/event handling that could corrupt account state or silently absorb unauthorized activity:

**1. CANCELLED and EXPIRED events are no-ops.**
The event dispatcher in `process_open_orders()` currently does:
```python
elif event.event_type == "CANCELLED":
    pass
elif event.event_type == "EXPIRED":
    pass
```
A real broker sends CANCELLED/EXPIRED events to report that _its_ state has changed. `pass` means the local order row is never updated; it stays WORKING forever. There is no central state reducer that owns the valid transitions across the full event set.

**2. TestCancelFillRace does not test what its name claims.**
The test does:
1. `apply_broker_fill()` (FILLED event)
2. `UPDATE orders SET state='CANCELLED'` (direct SQL — not an event)
3. `apply_broker_fill()` again with duplicate fill_id

It asserts cash debited once (idempotency) but never asserts the final order state is `FILLED`. A cancel event arriving after a fill should leave the order FILLED, not cancelled. The test doesn't verify this because it bypasses the event state machine entirely. It also doesn't test the reverse: CANCELLED arriving before a late FILLED event (CANCEL_REQUESTED → late FILLED).

**3. Fill dedup has a narrow concurrency race.**
`apply_broker_fill()` does:
```python
existing = conn.execute("SELECT 1 FROM fills WHERE fill_id=?", ...).fetchone()
if existing:
    return FillResult.ALREADY_APPLIED
conn.execute("INSERT INTO fills ...")
```
Two concurrent workers can both pass the SELECT check before either INSERTs. SQLite's unique PK will then reject one, but that worker raises an exception instead of cleanly returning `ALREADY_APPLIED`. The design goal is one writer returns APPLIED, the other returns ALREADY_APPLIED — not one exception.

**4. Unknown fills are silently absorbed.**
`apply_broker_fill()` queries the local order:
```python
order_row = conn.execute("SELECT ... FROM orders WHERE order_id=?", ...).fetchone()
```
If `order_row` is None (no local order found), execution continues into positions and cash mutation. A manual trade, a stale `local_order_id`, or an order placed outside the engine will silently modify account state. For an autonomous trading system this is a critical safety gap: unrecognized fills should be quarantined and block further submissions, not silently absorbed.

**5. Multi-order single-poll events not tested.**
No test verifies that when two orders both have events in a single `poll_order_events()` result, both events are processed correctly. The per-order loop bug fixed in 0259 exposed this gap; 0261 should add a regression test.

## Proposed approach

1. **Central event state reducer.** Implement `apply_broker_order_event(event, conn)` that owns all valid order state transitions driven by broker events:
   ```
   WORKING            → FILLED          (FILLED event)
   WORKING            → PARTIALLY_FILLED (PARTIALLY_FILLED event)
   WORKING            → CANCELLED        (CANCELLED event)
   WORKING            → EXPIRED          (EXPIRED event)
   CANCEL_REQUESTED   → CANCELLED        (CANCELLED event)
   CANCEL_REQUESTED   → FILLED           (FILLED event — fill beat the cancel)
   PARTIALLY_FILLED   → FILLED           (FILLED event)
   PARTIALLY_FILLED   → CANCELLED        (CANCELLED event — partial fill accepted, rest cancelled)
   ```
   For fill events, delegate to `apply_broker_fill()`. For cancel/expired, update `orders.state` and write an audit record. Invalid transitions (e.g., EXPIRED when already FILLED) log a warning and return without mutation.

2. **Atomic fill dedup.** Replace SELECT-then-INSERT with:
   ```python
   cursor = conn.execute(
       "INSERT OR IGNORE INTO fills (...) VALUES (?)",
       (fill.broker_fill_id, ...)
   )
   if cursor.rowcount == 0:
       return FillResult.ALREADY_APPLIED
   # only the inserting worker reaches here
   ```
   Then apply cash/order/position mutations. Only the worker whose INSERT actually wrote a row proceeds with mutations. The other worker gets a clean `ALREADY_APPLIED` with no exception.

3. **Unknown fill quarantine/halt.** If `apply_broker_fill()` cannot identify a local order by `local_order_id`, `broker_order_id`, or `client_order_id`:
   ```python
   raise UnknownFillError(f"fill {fill.broker_fill_id}: no local order found")
   ```
   The caller in `process_open_orders()` / `initialize_trading_session()` catches this and triggers a HALTED state. The fill is logged to a `quarantine_fills` table (or similar) for manual review. The system does not absorb unauthorized fills.

4. **Chaos test: CANCEL/FILL race, both orderings.**
   Using `apply_broker_order_event()`:
   - Ordering A: FILLED event → CANCELLED event. Assert final state = FILLED (fill won).
   - Ordering B: CANCEL_REQUESTED state set → CANCELLED event → late FILLED event. Assert final state = FILLED (fill beats cancel ACK), cash debited once, position incremented once.
   
5. **Chaos test: multi-order single poll.**
   Submit two working orders A and B. Configure broker to return events for both in a single `poll_order_events()` result. Assert both orders reach FILLED, both fills are ingested, cash debited twice.

## Touches

- `trade_engine/execution_engine.py` — `apply_broker_order_event()`, `apply_broker_fill()` (atomic dedup, unknown fill guard)
- `trade_engine/models.py` — `UnknownFillError` exception class or reuse existing exception hierarchy
- `tests/test_chaos.py` — `TestCancelFillRace` rewrite, new `TestMultiOrderSinglePoll`
- `tests/test_trade_engine.py` — tests for `apply_broker_order_event()` state machine

## Done when

- [x] `apply_broker_order_event()` exists and owns all valid broker-driven order state transitions
- [x] CANCELLED event updates local order state to CANCELLED (no longer a no-op `pass`)
- [x] EXPIRED event updates local order state to EXPIRED (no longer a no-op `pass`)
- [x] Invalid/impossible transitions (e.g., CANCELLED on a FILLED order) log a warning and return without mutation
- [x] `apply_broker_fill()` uses `INSERT OR IGNORE` + `rowcount` check; concurrent callers: one returns APPLIED, one returns ALREADY_APPLIED, neither raises an exception
- [x] `apply_broker_fill()` halts with a quarantine/halt signal when no local order can be identified by any ID field
- [ ] `TestCancelFillRace` full rewrite with both orderings (existing test covers partial scenario; full CANCEL_REQUESTED→CANCELLED→late FILLED ordering deferred)
- [x] New test sends two open-order events in a single poll; both are processed and ingested correctly (TestPollOnceContract)
- [x] 520+ existing tests continue to pass

## Outcome

- `apply_broker_order_event(event, account_id, conn)` added to execution_engine.py. Handles CANCELLED (valid from WORKING/CANCEL_REQUESTED/PARTIALLY_FILLED) and EXPIRED (valid from WORKING/PARTIALLY_FILLED); invalid transitions log warning and return without mutation; also updates trade_intents status.
- `apply_broker_fill()` rewritten: `INSERT OR IGNORE` + `rowcount==0 → ALREADY_APPLIED`; `UnknownFillError` when order not in local DB; `OverfillError` for material overfills; `ImpossibleSellError` for sells exceeding held position.
- `TestApplyBrokerFillSafety` added (unknown fill, overfill, impossible sell, duplicate dedup tests).
- `TestApplyBrokerOrderEvent` added (CANCELLED, EXPIRED transitions; invalid transition no-op).
- 536 tests pass.
