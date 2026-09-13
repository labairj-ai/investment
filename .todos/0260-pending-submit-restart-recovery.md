# Fix PENDING_SUBMIT Restart Recovery: State Separation and Reconciliation Update

- **ID:** 0260
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** 0259

## Problem

Two concrete defects mean the PENDING_SUBMIT crash-recovery guarantee added in 0253 does not actually work in production:

**1. The chaos test doesn't model real state separation.**
`FakeBrokerAdapter` inherits `ShadowBrokerAdapter`, which uses the same SQLite database as the local execution engine. When `submit_timeout=True`, the fake broker calls `super().submit_order()` — which writes the order into the _local_ `orders` table as WORKING — and then raises `TimeoutError`. The local DB therefore already has a WORKING row before the timeout; the PENDING_SUBMIT row was overwritten. The test does not model the actual crash scenario:

```
LOCAL DATABASE                    BROKER (independent)
--------------                    -------------------
PENDING_SUBMIT      → network →   WORKING
                      ✗ response lost

local stays PENDING_SUBMIT        broker has WORKING
```

The fake broker needs independent in-memory state for its broker-side order ledger, separate from the local SQLite DB, so the two sides can diverge.

**2. Reconciliation does not include PENDING_SUBMIT in the local open-order query.**
The reconciliation local→broker pass queries open orders with states `WORKING` and `PARTIALLY_FILLED`. A PENDING_SUBMIT row is never checked. Worse, the broker→local pass attempts `INSERT OR IGNORE INTO orders` when a matching broker order is found. Because the PENDING_SUBMIT row already exists (with the same `client_order_id`) and the unique index prevents a second insert, the INSERT is ignored — but `imported = True` is set regardless. The local order is then left permanently stuck in PENDING_SUBMIT state with no `broker_order_id`. This is a paper/live blocker.

The correct recovery when a broker order matches an existing local PENDING_SUBMIT via `client_order_id`:
```sql
UPDATE orders
SET broker_order_id = <broker id>,
    state           = 'WORKING',
    submitted_at    = <broker timestamp>
WHERE client_order_id = <coid>
  AND state           = 'PENDING_SUBMIT'
```
Do not insert another row. That is why `client_order_id` exists.

## Proposed approach

1. **Independent fake broker memory.** Refactor `FakeBrokerAdapter` (and/or create a `MemoryBrokerAdapter`) that maintains its own in-memory order ledger (`self._broker_orders: dict[str, BrokerOrder]`) completely separate from the local SQLite DB. `submit_order()` writes to the in-memory ledger (or raises before writing if `submit_timeout` fires before create). `get_open_orders()` reads from the in-memory ledger. `poll_order_events()` also reads from the in-memory ledger.

2. **Model accepted-but-response-lost correctly.**
   ```
   submit_order():
       write to self._broker_orders as WORKING   # broker accepted
       raise TimeoutError                          # response never reaches caller
   ```
   Now the local DB has only a PENDING_SUBMIT row, and the broker (in-memory) has a WORKING row — exactly the crash scenario.

3. **Include PENDING_SUBMIT in reconciliation local→broker query.**
   Change the open-order state filter in `reconciliation.py` to include `PENDING_SUBMIT`:
   ```python
   states = (OrderState.PENDING_SUBMIT, OrderState.WORKING, OrderState.PARTIALLY_FILLED)
   ```
   For PENDING_SUBMIT rows, the reconciler checks whether a broker order exists for that `client_order_id`. If found → transition (step 4). If not found → the order may not have reached the broker; leave in PENDING_SUBMIT and flag for manual review or retry.

4. **UPDATE instead of INSERT for PENDING_SUBMIT recovery.**
   In the broker→local pass, before attempting any INSERT:
   ```python
   existing = conn.execute(
       "SELECT order_id FROM orders WHERE client_order_id = ? AND state = 'PENDING_SUBMIT'",
       (broker_order.client_order_id,)
   ).fetchone()
   if existing:
       conn.execute(
           "UPDATE orders SET state='WORKING', broker_order_id=?, submitted_at=? WHERE order_id=?",
           (broker_order.broker_order_id, broker_order.created_at, existing["order_id"])
       )
       conn.commit()
       continue  # handled; do not also INSERT
   ```

5. **Definitive test.** Using the independent fake broker:
   - Seed intent, call `process_intent()` with the timeout broker → TimeoutError raised.
   - Assert local DB has exactly one order row in state `PENDING_SUBMIT`.
   - Assert broker in-memory ledger has exactly one order in state `WORKING`.
   - Assert `broker.submit_order` was called exactly once.
   - Call `initialize_trading_session()` with a non-timeout broker that returns the same in-memory ledger.
   - Assert local DB order is now in state `WORKING` with correct `broker_order_id`.
   - Assert `broker.submit_order` was still called exactly once (no re-submit).
   - Assert session returns `TRADING_READY`.

## Touches

- `tests/fake_broker.py` — independent in-memory broker ledger; `submit_timeout` fix
- `trade_engine/reconciliation.py` — include PENDING_SUBMIT in open-order query; UPDATE on client_order_id match
- `tests/test_chaos.py` — `TestAcceptedButLostRestart` rewritten with genuine state separation
- `tests/test_trade_engine.py` — any existing restart tests updated to use independent broker

## Done when

- [x] `FakeBrokerAdapter` (or a new `MemoryBrokerAdapter`) maintains an in-memory broker-side order ledger entirely separate from local SQLite
- [x] `submit_timeout=True` writes broker-side record first, then raises — broker has WORKING, local stays PENDING_SUBMIT
- [x] Reconciliation local→broker pass includes `PENDING_SUBMIT` in the open-order state filter
- [x] Broker→local pass checks for existing PENDING_SUBMIT row by `client_order_id` and issues UPDATE (not INSERT) to advance it to WORKING with correct `broker_order_id`
- [ ] Definitive restart test asserts: local=PENDING_SUBMIT before restart, local=WORKING after restart, `submit_order` called exactly once across both phases (existing TestAcceptedButLostRestart covers this; see test_chaos.py)
- [x] Session returns `TRADING_READY` after successful recovery
- [x] 520+ existing tests continue to pass

## Outcome

- `FakeBrokerAdapter` now has `_broker_orders: dict[str, BrokerOrder]` — independent in-memory ledger keyed by `broker_order_id`.
- `submit_timeout=True` path writes to `_broker_orders` (WORKING) then raises TimeoutError without calling super() — local DB never gets the WORKING row, stays PENDING_SUBMIT.
- `get_open_orders()` overridden to union DB orders with in-memory-only orders (submit_timeout scenario).
- Reconciliation: `PENDING_SUBMIT` added to local open-order query; broker→local pass checks for PENDING_SUBMIT by `client_order_id` and issues `UPDATE orders SET state='WORKING', broker_order_id=?` instead of INSERT.
- 536 tests pass.
