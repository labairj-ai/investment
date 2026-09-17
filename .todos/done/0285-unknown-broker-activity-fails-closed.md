# Quarantine and Halt on Unresolvable Broker Activity

- **ID:** 0285
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0284

## Problem

`process_open_orders()` warns and skips any event it cannot map through the three-tier local/broker/client_order_id resolver. The resolver's contract requires callers to halt when an order cannot be uniquely resolved, but the call site violates that contract with a log-and-continue. If the skipped event is a fill, a real economic event is silently discarded — cash and positions are never updated, yet no error is surfaced. The same silent-skip applies to locally-open orders that unexpectedly disappear from broker lookup and to broker-side activity (orders or fills) for which no local record exists. On a dedicated brokerage account any of these conditions signals an unexpected state that requires human review, not silent continuation.

## Proposed approach

- **Unresolvable events:** when `resolve_local_order_id()` cannot match an event to a local order, treat it as unknown broker activity — append a `RECONCILIATION_UNAVAILABLE` (or new `UNKNOWN_BROKER_ACTIVITY`) discrepancy, halt new submissions, and do not process the event further.
- **Locally-open orders missing at broker:** if `broker.get_order()` returns `None` for a WORKING/PARTIALLY_FILLED local order, treat as a blocking discrepancy rather than silently skipping the row.
- **Unexpected broker-only activity:** orders or fills the broker reports that have no local record after exhausting all three resolver tiers should be quarantined (logged to a `quarantine_events` table or equivalent) and block new submissions until reconciled.
- Add tests for each path: unresolvable FILLED event → HALTED; locally-open order missing at broker → HALTED; unexpected broker fill with no local order → HALTED/quarantine.

## Touches

- `trade_engine/execution_engine.py` — `process_open_orders()` event loop; resolver call site
- `trade_engine/reconciliation.py` — possibly a new `DiscrepancyKind` or reuse `RECONCILIATION_UNAVAILABLE`
- `tests/test_chaos.py` — new halt-on-unknown-activity tests
- `tests/fake_broker.py` — mode to emit events with unresolvable IDs

## Done when

- [x] Unresolvable event (no local order match after all three resolver tiers) → blocking discrepancy, no silent skip, no fill applied
- [x] Locally-open order returning `None` from `broker.get_order()` → blocking discrepancy; cycle halts before new intent evaluation
- [x] Unexpected broker-only activity with no local record → quarantine + halt; not a warning
- [x] Chaos tests cover all three paths and assert HALTED (not a warning log)
- [x] All existing 589 tests still pass

## Outcome

Changed `process_open_orders()` warn-skip at unresolvable events to raise `BrokerSettlementIndeterminate`. Changed silent `continue` for `get_order()` returning None to raise `BrokerSettlementIndeterminate`. `sync_broker_state()` (0284) also raises BSI on unresolvable events. Added `unresolvable_events` mode to `FakeBrokerAdapter` (emits a phantom fill with a bogus broker_order_id). `ShadowBrokerAdapter.get_order()` fixed to look up by broker_order_id OR order_id — exposed a latent bug in crash-recovery reconciliation path. 4 chaos tests added in `TestUnknownBrokerActivityFails`.
