# Restart/Reconnect Recovery: Reconcile Before TRADING_READY

- **ID:** 0242
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0238, 0240

## Problem

If the process restarts, it has no startup sequence that prevents it from submitting duplicate orders or acting on stale local state. For shadow mode this doesn't matter — local state is authoritative. For paper/live mode, a reboot that skips reconciliation can:

- Resubmit an order that was already filled while the process was down
- Miss fills that arrived during the downtime and thus have incorrect position/cash state
- Submit against positions that changed overnight (assignment, dividend, corporate action)

The process must not accept new order submissions until it has proven local state matches broker state.

## Proposed approach

**Add a `TradingReadyState` and startup sequence:**

```python
class TradingReadyState(str, Enum):
    INITIALIZING = "INITIALIZING"
    RECONCILING = "RECONCILING"
    TRADING_READY = "TRADING_READY"
    HALTED = "HALTED"
```

**Startup sequence in a new function `initialize_trading_session()`:**

```python
def initialize_trading_session(
    account_id: str,
    conn: sqlite3.Connection,
    broker: BrokerAdapter,
) -> TradingReadyState:
    # 1. Connect / verify broker reachable: broker.get_broker_account()
    # 2. Retrieve positions: broker.get_positions()  
    # 3. Retrieve open orders: broker.get_orders()
    # 4. Fetch fills since last sync: broker.get_fills(since=last_fill_at)
    # 5. Import any broker-reported fills not yet in local DB
    # 6. Reconcile: reconcile(account_id, conn, broker)
    # 7. If reconciliation passes → return TRADING_READY
    # 8. If reconciliation fails → return HALTED (do not submit orders)
```

**Gate in `run_execution_cycle()`:**

```python
def run_execution_cycle(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
    *,
    trading_state: TradingReadyState = TradingReadyState.TRADING_READY,
) -> dict:
    if trading_state != TradingReadyState.TRADING_READY:
        return {**_HALTED_BASE, "halt_reason": "NOT_TRADING_READY"}
    ...
```

For shadow mode, `initialize_trading_session()` always returns `TRADING_READY` immediately (shadow is always coherent).

**Fill import step:**
When broker reports fills not in the local `fills` table (by `broker_fill_id`), import them: create the fill row, update position_snapshots and cash. This prevents reprocessing the same fills on the next startup.

**Idempotency guard:**
Before submitting any order, check whether a `broker_order_id` already exists for this intent. If so, skip submission — the order was already placed in a prior session.

**Tests:**
- Shadow: `initialize_trading_session()` returns `TRADING_READY` immediately
- With unreconciled state: returns `HALTED`
- `run_execution_cycle()` with `trading_state=INITIALIZING` returns NOT_TRADING_READY
- Fill import: broker fill not in DB → imported on startup; not duplicated on second startup

## Touches

- `trade_engine/execution_engine.py` — `initialize_trading_session()`, `TradingReadyState`, gate in `run_execution_cycle()`
- `trade_engine/reconciliation.py` — used by `initialize_trading_session()` (depends on 0240)
- `trade_engine/broker_adapter.py` — `get_fills(since=None)` already in 0237 protocol
- `agent_db.py` — track `last_fill_synced_at` per account (new column or separate table)
- `tests/test_trade_engine.py` — startup sequence tests
- `serve.py` — call `initialize_trading_session()` once at startup before starting the cycle timer

## Done when

- [ ] `TradingReadyState` enum exists with INITIALIZING, RECONCILING, TRADING_READY, HALTED
- [ ] `initialize_trading_session()` runs the full sequence and returns the appropriate state
- [ ] Shadow mode always returns `TRADING_READY` from `initialize_trading_session()`
- [ ] `run_execution_cycle()` returns NOT_TRADING_READY when trading_state != TRADING_READY
- [ ] Broker fills not in local DB are imported during startup, not duplicated on second startup
- [ ] Tests cover shadow pass-through and halted-on-mismatch paths
