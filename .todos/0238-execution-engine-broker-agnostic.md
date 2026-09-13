# ExecutionEngine Must Accept BrokerAdapter — Remove Direct ShadowBroker Instantiation

- **ID:** 0238
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0237

## Problem

`process_intent()` (`execution_engine.py:310`) and `process_open_orders()` (`execution_engine.py:389`) both instantiate `ShadowBroker(conn)` directly. The desired architecture is:

```
ExecutionEngine
      ↓
BrokerAdapter
   ↙       ↘
Shadow    Paper
```

not:

```
ExecutionEngine → ShadowBroker (direct)
BrokerAdapter (exists but never used by ExecutionEngine)
```

`BrokerAdapter` exists in `broker_adapter.py` but has never been threaded into the actual execution path. This is now the biggest architectural gap before paper integration.

## Proposed approach

**1. Thread adapter through `process_intent()` and `process_open_orders()`:**

```python
def process_intent(
    intent_id: str,
    conn: sqlite3.Connection,
    broker: BrokerAdapter,
) -> ExecutionResult:
    ...
    order = broker.submit_order(intent)
    quote = broker.get_quote(intent.symbol)  # via adapter, not market_data directly
    fill = broker.attempt_fill(order, quote)  # if adapter exposes this
    ...

def process_open_orders(
    account_id: str,
    conn: sqlite3.Connection,
    broker: BrokerAdapter,
) -> tuple[list[Fill], int, int]:
    ...
```

**2. Thread adapter through `run_execution_cycle()`:**

```python
def run_execution_cycle(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
) -> dict:
    if broker is None:
        broker = ShadowBrokerAdapter(conn, account_id)
    ...
    process_intent(intent_id, conn, broker)
    process_open_orders(account_id, conn, broker)
```

`broker=None` default creates a `ShadowBrokerAdapter` for backward compatibility so `serve.py` doesn't have to change immediately. Over time callers pass an explicit adapter.

**3. Update `ShadowBrokerAdapter` to expose `attempt_fill()`:**
Currently `ShadowBroker.attempt_fill()` is the core fill path. `ShadowBrokerAdapter` wraps it. Add `attempt_fill(order, quote) -> Optional[Fill]` to the `BrokerAdapter` protocol — for live brokers this method is a no-op (fills arrive asynchronously via webhook/websocket, not a synchronous call).

**4. Update `serve.py`:**
The `/api/trade-engine/run` endpoint currently calls `run_execution_cycle(account_id, conn)`. No change required if the `broker=None` default instantiates `ShadowBrokerAdapter` transparently.

**5. All shadow tests must pass through the adapter:**
The existing 172 tests call `process_intent` / `process_open_orders` / `run_execution_cycle` directly. Update the test helpers or use the `broker=None` default so they run through `ShadowBrokerAdapter` without knowing it.

## Touches

- `trade_engine/execution_engine.py` — `process_intent()`, `process_open_orders()`, `run_execution_cycle()` signatures and bodies
- `trade_engine/broker_adapter.py` — add `attempt_fill()` to protocol; keep `ShadowBrokerAdapter` working
- `trade_engine/shadow_broker.py` — no changes required
- `serve.py` — verify no change needed with `broker=None` default
- `tests/test_trade_engine.py` — verify tests pass with adapter default

## Done when

- [ ] `process_intent()` and `process_open_orders()` accept a `BrokerAdapter` parameter
- [ ] `run_execution_cycle()` accepts `broker: Optional[BrokerAdapter] = None`; default creates `ShadowBrokerAdapter`
- [ ] No direct `ShadowBroker(conn)` instantiation inside `process_intent` or `process_open_orders`
- [ ] All 172 existing tests pass unchanged
- [ ] `BrokerAdapter` protocol includes `attempt_fill(order, quote) -> Optional[Fill]`
