# Respect BrokerOrderAck normalized_state Instead of Hardcoding WORKING

- **ID:** 0271
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0267, 0268

## Problem

`BrokerOrderAck.normalized_state` was added in 0267 to let the adapter communicate the broker's initial order state back to the execution engine. However, `process_intent()` ignores it entirely: after a successful `submit_order()` the engine always executes `UPDATE orders SET state='WORKING'`, even if the ACK says the broker returned `PENDING`, `REJECTED`, or even an immediate `FILLED`. For a real broker (Alpaca/IBKR) a rejected order would be silently treated as WORKING, never re-checked, and the intent would be considered "filled" only after a timeout rather than immediately cleaned up.

## Proposed approach

- In `process_intent()`, branch on `ack.normalized_state` after submit:
  - `WORKING` (default): existing UPDATE to `state='WORKING'`
  - `PENDING`: UPDATE to `state='PENDING_SUBMIT'` (broker received but hasn't accepted yet; let reconciliation promote it)
  - `REJECTED`: UPDATE to `state='REJECTED'`; no fill expected; log warning
  - `FILLED`: call `apply_broker_fill()` immediately with a synthetic fill constructed from the ACK; skip the WORKING state entirely
- `BrokerAdapter.get_order()` should return a `BrokerOrder` (broker-native view) rather than relying on local `Order`; document the contract. `cancel_order()` should similarly return a normalized result indicating whether the cancel was accepted, rejected, or unknown.
- Add unit tests that drive each ACK state through `process_intent()` via `FakeBrokerAdapter` with a controllable `normalized_state` return value and assert the correct local state row afterward.

## Touches

- `trade_engine/execution_engine.py` — `process_intent()` ACK-state dispatch
- `trade_engine/broker_types.py` — document `normalized_state` valid values; add `BrokerCancelResult` if needed
- `trade_engine/broker_adapter.py` — `get_order()` and `cancel_order()` return-type contracts
- `tests/fake_broker.py` — support configurable `normalized_state` on `submit_order()` response
- `tests/test_trade_engine.py` — four-branch ACK state tests (PENDING/WORKING/REJECTED/FILLED)

## Done when

- [x] `process_intent()` branches on `ack.normalized_state`; WORKING, PENDING, REJECTED, and FILLED each produce the correct local `state` row
- [x] REJECTED ack → state='REJECTED', intent REJECTED, early return (no WORKING orphan)
- [x] FILLED ack → synthetic fill via apply_broker_fill(), order reaches FILLED
- [x] PENDING ack → state explicitly kept/set to PENDING_SUBMIT (overrides shadow's WORKING advance)
- [x] Terminal-state guard added: process_intent() short-circuits if existing order is FILLED/CANCELLED/REJECTED/EXPIRED
- [x] 558 tests pass

## Outcome

Four-branch dispatch in `process_intent()` on `_ack_state`. REJECTED: UPDATE state='REJECTED' + intent REJECTED + early return. PENDING: UPDATE state='PENDING_SUBMIT' (explicit, overrides ShadowBroker's advance). FILLED: UPDATE state='WORKING' then synthesize BrokerFill with broker_fill_id=`ack-fill-{broker_order_id}`, apply_broker_fill() → FILLED. WORKING (default): same as before. Terminal-state guard prevents re-submission for already-terminal intents. FakeBrokerAdapter gained `ack_state` param.
