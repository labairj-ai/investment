# Normalized Broker Domain Models (BrokerQuote, BrokerPosition, etc.)

- **ID:** 0237
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

The abstraction currently depends on a concrete implementation: `BrokerAdapter.get_quote()` returns `Optional[Quote]`, and `Quote` is imported from `shadow_broker.py`. Any paper/live adapter that implements `BrokerAdapter` must also import from a shadow module, which is backwards. `BrokerAdapter.get_positions()` returns an untyped `list`, and the `ShadowBrokerAdapter` implementation returns internal `(symbol, qty)` tuples — making the contract impossible to enforce.

The goal is for each external broker adapter to translate its native objects to broker-neutral types, not to expose broker-specific schemas through the system.

## Proposed approach

**1. Create `trade_engine/broker_types.py`:**

```python
from typing import NamedTuple, Optional

class BrokerQuote(NamedTuple):
    bid: float
    ask: float
    symbol: str
    market_timestamp: Optional[str] = None
    retrieved_at: Optional[str] = None
    source: str = "unknown"

class BrokerPosition(NamedTuple):
    symbol: str
    qty: float
    avg_cost: float
    instrument_type: str = "EQUITY"
    market_price: Optional[float] = None
    market_value: Optional[float] = None

class BrokerOrder(NamedTuple):
    broker_order_id: str
    symbol: str
    side: str
    quantity: float
    fill_qty: float
    state: str
    limit_price: Optional[float] = None

class BrokerFill(NamedTuple):
    broker_fill_id: str
    broker_order_id: str
    symbol: str
    side: str
    qty: float
    price: float
    filled_at: str
    fee: float = 0.0

class BrokerAccountState(NamedTuple):
    account_id: str
    cash: float
    nav: float
    buying_power: float
```

**2. Update `trade_engine/broker_adapter.py`:**
- Import from `broker_types` instead of `shadow_broker`
- Change `get_quote()` return type to `Optional[BrokerQuote]`
- Change `get_positions()` return type to `list[BrokerPosition]`
- Add `get_orders(account_id) -> list[BrokerOrder]`
- Add `get_fills(account_id, since=None) -> list[BrokerFill]`
- Add `get_broker_account(account_id) -> BrokerAccountState`

**3. Update `trade_engine/shadow_broker.py`:**
- Keep `Quote` as a type alias: `Quote = BrokerQuote` (for backward compat during transition)
- `Quote` still lives here but re-exported from `broker_types`

**4. Update `trade_engine/market_data.py`:**
- Import `BrokerQuote` from `broker_types`; use it as the return type for `_get_quote()` etc.

**5. `ShadowBrokerAdapter` in `broker_adapter.py`:**
- `get_positions()` returns `list[BrokerPosition]` from `position_snapshots` table
- `get_quote()` returns `BrokerQuote` (wrapping shadow market data)
- `get_orders()` returns `list[BrokerOrder]` from `orders` table
- `get_fills()` returns `list[BrokerFill]` from `fills` table
- `get_broker_account()` returns `BrokerAccountState` from `trading_accounts`

## Touches

- `trade_engine/broker_types.py` — new file
- `trade_engine/broker_adapter.py` — updated interface and ShadowBrokerAdapter impl
- `trade_engine/shadow_broker.py` — Quote alias; imports from broker_types
- `trade_engine/market_data.py` — return type updates
- `trade_engine/execution_engine.py` — import Quote from broker_types (not shadow_broker)
- `tests/test_trade_engine.py` — update Quote imports if needed

## Done when

- [ ] `broker_types.py` exists with all 5 normalized types
- [ ] `BrokerAdapter.get_positions()` is typed `list[BrokerPosition]`
- [ ] `BrokerAdapter.get_quote()` is typed `Optional[BrokerQuote]`
- [ ] `BrokerAdapter` protocol includes `get_orders()`, `get_fills()`, `get_broker_account()`
- [ ] `ShadowBrokerAdapter` implements all new methods correctly
- [ ] `Quote` alias in `shadow_broker.py` preserved for backward compat
- [ ] All 172 tests pass
