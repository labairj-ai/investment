# Make ACK State Reducer Exhaustive and Fail-Closed

- **ID:** 0280
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0271, 0278

## Problem

`process_intent()` explicitly handles only `REJECTED`, `PENDING`, and `FILLED` in the post-submit ACK dispatch; all other normalized states fall through to a default `else` branch that writes `state='WORKING'`. `BrokerOrderState` supports eight values: `PENDING`, `WORKING`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `EXPIRED`, `REJECTED`, and `ERROR`. An immediate broker response of `PARTIALLY_FILLED` (realistic for a marketable limit order that sweeps partial liquidity), `CANCELLED`, `EXPIRED`, or `ERROR` is silently normalized to `WORKING` — a misclassification that leaves intent status, cash, and position in incorrect states and undermines the purpose of the ACK.

## Proposed approach

- Replace the current `if/elif/else` structure with a single exhaustive reducer mapping every `BrokerOrderState` value to a specific local transition. No default-to-WORKING fallback.
- `WORKING` → write `state='WORKING'`, attach `broker_order_id` (existing behavior, now explicit).
- `PARTIALLY_FILLED` → attach `broker_order_id`, write `state='WORKING'` (open order), call `get_fills_for_order()`, apply each fill via `apply_broker_fill()`; let the fill ledger determine aggregate state.
- `FILLED` → existing path from 0273/0278: `get_fills_for_order()` + `BrokerSettlementIndeterminate` on failure/empty.
- `CANCELLED` / `EXPIRED` / `REJECTED` → write terminal order state, update intent status to match.
- `ERROR` or any unknown/unrecognized string → raise `BrokerSettlementIndeterminate` (fail closed; do not write WORKING).
- Add one test per `BrokerOrderState` value verifying the correct local state transition, intent status, and whether fills were applied.

## Touches

- `trade_engine/execution_engine.py` — ACK dispatch in `process_intent()`
- `tests/test_trade_engine.py` or `tests/test_chaos.py` — one test per ACK state value

## Done when

- [ ] Every `BrokerOrderState` value has an explicit branch; no default-to-WORKING fallback
- [ ] `PARTIALLY_FILLED` ACK calls `get_fills_for_order()` and applies fills; does not write a terminal state manually
- [ ] `CANCELLED` / `EXPIRED` / `REJECTED` ACK writes terminal order state and updates intent status
- [ ] `ERROR` or unknown ACK state raises `BrokerSettlementIndeterminate` (fail closed)
- [ ] One test per `BrokerOrderState` value asserting correct order state, intent status, and fill ledger
- [ ] All existing 566 tests still pass
