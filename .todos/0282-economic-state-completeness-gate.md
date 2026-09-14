# Fail Closed on All Paths Where Broker Confirms Execution but Fills Unavailable

- **ID:** 0282
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0278, 0279

## Problem

Three execution paths that reach authoritative-fill retrieval currently fail open when fills are unavailable, even though the broker has confirmed execution occurred. (1) **PARTIALLY_FILLED ACK** in `process_intent()`: `get_fills_for_order()` failure is caught and turned into an empty list; the engine returns normally while local cash and positions are already known to be wrong — subsequent intents are not blocked. (2) **PARTIALLY_FILLED recovery** in reconciliation section 3c: `get_fills_for_order()` failure is silently swallowed as empty; no blocking discrepancy is added; the order is written WORKING and the session can reach TRADING_READY with stale economics. (3) **FILLED recovery** in reconciliation section 3c: same issue — the fills-failure except branch produces an empty list, the order is updated to WORKING, and no blocking discrepancy is appended, so `blocks_submission` may remain False.

## Proposed approach

Apply the same fail-closed principle as 0278 to all three paths:

- **PARTIALLY_FILLED ACK** (`process_intent()`): raise `BrokerSettlementIndeterminate` when `get_fills_for_order()` raises or returns empty. The broker confirmed partial execution; the economic state is known to be wrong; new exposure must stop.
- **PARTIALLY_FILLED recovery** (reconciliation section 3c): replace the `except Exception: _pf_reco_fills = []` pattern with an `except` that appends `Discrepancy(kind=RECONCILIATION_UNAVAILABLE, detail="Broker reports PARTIALLY_FILLED but authoritative fills unavailable")` to `discrepancies`. Do not continue with an empty fill list.
- **FILLED recovery** (reconciliation section 3c): same change — replace the silent `except Exception: _reco_fills = []` with a blocking `RECONCILIATION_UNAVAILABLE` discrepancy when the fills endpoint raises.
- Add tests for all three paths: PARTIALLY_FILLED ACK + fill lookup failure → `BrokerSettlementIndeterminate`; PARTIALLY_FILLED reconciliation recovery + fill lookup failure → blocking discrepancy; FILLED reconciliation recovery + fill lookup failure → blocking discrepancy.

## Touches

- `trade_engine/execution_engine.py` — PARTIALLY_FILLED ACK branch in `process_intent()`
- `trade_engine/reconciliation.py` — section 3c PARTIALLY_FILLED and FILLED recovery branches
- `tests/test_chaos.py` — three new tests covering each fail-closed path

## Done when

- [x] PARTIALLY_FILLED ACK + `get_fills_for_order()` raises or returns empty → `BrokerSettlementIndeterminate`; subsequent intents blocked
- [x] PARTIALLY_FILLED reconciliation recovery + fills endpoint failure → `RECONCILIATION_UNAVAILABLE` discrepancy; `blocks_submission=True`
- [x] FILLED reconciliation recovery + fills endpoint failure → `RECONCILIATION_UNAVAILABLE` discrepancy; `blocks_submission=True`
- [x] No path silently swallows fill-lookup failure with an empty list when broker has confirmed execution
- [x] All three new test scenarios pass; all existing 580 tests still pass (589 pass total)

## Outcome

Three paths fixed: (1) PARTIALLY_FILLED ACK branch in `process_intent()` — changed `except Exception: _pf_fills = []` to raise `BrokerSettlementIndeterminate` on both exception and empty return. (2) PARTIALLY_FILLED recovery in `reconciliation.py` section 3c — exception now appends `RECONCILIATION_UNAVAILABLE` discrepancy + empty-return also appends one. (3) FILLED recovery in section 3c — same pattern. Added `TestPartiallyFilledACKFailClosed` with 4 tests (2 for ACK path, 2 for reco recovery).
