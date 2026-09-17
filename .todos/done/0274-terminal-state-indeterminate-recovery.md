# Respect Broker Terminal States During PENDING_SUBMIT Recovery

- **ID:** 0274
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0270

## Problem

Reconciliation section 3c calls `broker.find_order_by_client_order_id()` to recover PENDING_SUBMIT rows, but always transitions the local order to WORKING regardless of what `bo.state` actually says. If the broker filled, cancelled, or rejected the order before the app restarted, the local ledger still records WORKING — undermining the crash/restart protection built in 0265/0270. Separately, `ShadowBrokerAdapter.find_order_by_client_order_id()` explicitly excludes CANCELLED, REJECTED, EXPIRED, and FILLED rows from its query, so it cannot recover terminal-state orders at all even if the adapter knew about them.

## Proposed approach

- In reconciliation section 3c, apply a normalized reducer on `bo.state` instead of always writing WORKING:
  - `PENDING` → keep `PENDING_SUBMIT`
  - `WORKING` → WORKING
  - `PARTIALLY_FILLED` → ingest fills via `apply_broker_fill()` → PARTIALLY_FILLED
  - `FILLED` → ingest authoritative fills → FILLED
  - `CANCELLED` → CANCELLED; update intent to CANCELLED
  - `REJECTED` → REJECTED; update intent to REJECTED
  - `EXPIRED` → EXPIRED
  - unknown/unrecognized → HALTED (RECONCILIATION_UNAVAILABLE discrepancy)
- `ShadowBrokerAdapter.find_order_by_client_order_id()` must search all recent orders (remove the NOT IN terminal-state exclusion), so the reference implementation actually exercises the terminal-state recovery paths.
- `FakeBrokerAdapter.find_order_by_client_order_id()` already searches `_broker_orders` which can include terminal states — verify and document.
- Add chaos tests: (a) broker FILLED before restart → recovery produces FILLED with correct fill, not WORKING; (b) broker CANCELLED before restart → recovery produces CANCELLED; (c) broker REJECTED before restart → recovery produces REJECTED.

## Touches

- `trade_engine/reconciliation.py` — section 3c: replace `UPDATE state='WORKING'` with full reducer
- `trade_engine/broker_adapter.py` — `ShadowBrokerAdapter.find_order_by_client_order_id()`: remove terminal-state exclusion
- `tests/test_chaos.py` — terminal-state recovery tests (FILLED/CANCELLED/REJECTED before restart)

## Done when

- [x] Section 3c reducer maps all 7 broker states to correct local transitions; unknown → HALTED
- [x] Broker FILLED recovery ingests authoritative fills (via `get_fills_for_order()` from 0273), not synthetic data
- [x] Broker CANCELLED/REJECTED/EXPIRED recovery marks order and intent terminal correctly
- [x] `ShadowBrokerAdapter.find_order_by_client_order_id()` searches terminal orders too
- [x] Chaos tests: FILLED-before-restart, CANCELLED-before-restart, REJECTED-before-restart all pass

## Outcome

Reconciliation section 3c now applies a full state reducer on `bo.state` instead of always writing WORKING. FILLED → ingests authoritative fills via `get_fills_for_order()` (from 0273) and marks FILLED; CANCELLED/REJECTED/EXPIRED → marks terminal state and updates intent; WORKING/PARTIALLY_FILLED → writes WORKING; unknown → RECONCILIATION_UNAVAILABLE discrepancy. `ShadowBrokerAdapter.find_order_by_client_order_id()` now excludes only PENDING_SUBMIT (local-only state), so terminal orders are recoverable. Chaos tests `TestTerminalStateRecovery` cover FILLED/CANCELLED/REJECTED-before-restart scenarios.
