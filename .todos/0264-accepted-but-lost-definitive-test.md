# Prove Accepted-But-Lost Recovery With True State Separation

- **ID:** 0264
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0263

## Problem

The `TestAcceptedButLostRestart` chaos test does not prove the recovery it claims. `submit_timeout=True` correctly writes the broker-side order to `timeout_broker._broker_orders` and raises `TimeoutError`, leaving the local DB in `PENDING_SUBMIT`. However, the simulated restart then creates a brand-new `ShadowBrokerAdapter` that has no knowledge of `timeout_broker._broker_orders`. During reconciliation, `get_open_orders()` returns nothing from the broker side, so the `PENDING_SUBMIT → WORKING` transition is never exercised. The test therefore does not validate the recovery path at all. 0260 was marked done on the basis of this test, which was premature.

## Proposed approach

- Pass the same `FakeBrokerAdapter` instance (or its `_broker_orders` ledger) into the restart phase. Both `process_intent()` (crash phase) and `initialize_trading_session()` (recovery phase) must use the same broker object.
- The timeout flag can be cleared before the restart so that subsequent broker calls succeed (i.e. `broker._submit_timeout = False` after the crash).
- The test must:
  1. Call `process_intent()` → `TimeoutError` raised.
  2. Assert local DB: exactly one order row in state `PENDING_SUBMIT`.
  3. Assert `broker._broker_orders`: exactly one entry in state `WORKING` with a non-null `broker_order_id`.
  4. Call `initialize_trading_session()` with the **same broker instance**.
  5. Assert local DB: the order is now `WORKING`, `broker_order_id` column is populated and matches step 3.
  6. Assert `broker.submit_order` call count == 1 across both phases (no re-submission).
  7. Assert `initialize_trading_session()` returns `TRADING_READY`.
- The recovery depends on the broker identity resolver (0263): after recovery the local row will have `broker_order_id` set; the resolver must handle the interim state where `broker_order_id` is initially `None` in the PENDING_SUBMIT row.

## Touches

- `tests/test_chaos.py` — `TestAcceptedButLostRestart` rewrite
- `tests/fake_broker.py` — ensure `_broker_orders` ledger is accessible and broker can be reused across simulated restart phases
- `trade_engine/reconciliation.py` — verify UPDATE path is exercised with broker_order_id populated
- `.todos/0260-pending-submit-restart-recovery.md` — reopen or annotate as incomplete

## Done when

- [ ] After `process_intent()` raises `TimeoutError`, local DB has exactly one `PENDING_SUBMIT` order and `broker._broker_orders` has exactly one `WORKING` order
- [ ] After `initialize_trading_session()` with the same broker instance, local order transitions to `WORKING` with `broker_order_id` correctly populated
- [ ] `broker.submit_order` was called exactly once across both phases
- [ ] `initialize_trading_session()` returns `TRADING_READY`
- [ ] Test uses real event/reconciliation paths, not direct SQL mutation
- [ ] 536+ existing tests continue to pass
