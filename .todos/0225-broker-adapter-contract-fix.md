# Fix BrokerAdapter Contract: Circular Import, get_fills Bug, account_id

- **ID:** 0225
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`trade_engine/broker_adapter.py` has three bugs. (1) `get_fills()` passes `(self._conn, since)` to SQL where `(account_id, since)` is required — `self._conn` is a Connection object, not a string; also the method has no `account_id` parameter. (2) `get_quote()` does `from .execution_engine import _get_quote` — a backward circular dependency (BrokerAdapter should not depend on ExecutionEngine). (3) `get_account()` raises NotImplementedError instead of loading from `trading_accounts`.

## Proposed approach

1. Create `trade_engine/market_data.py`: extract `_get_quote`, `_get_executable_quote`, and `_get_mark_price` here. Both `execution_engine.py` and `broker_adapter.py` import from `market_data.py`. Dependency direction: ExecutionEngine → BrokerAdapter, both → market_data.
2. `ShadowBrokerAdapter.__init__`: accept and store `account_id: str`.
3. Fix `get_fills(account_id, since=None)`: correct parameter signature and SQL params `(account_id, since)`.
4. Implement `get_account(account_id)`: load row from `trading_accounts` via `self._conn`.
5. Add `BrokerAdapterContractTests` mixin in tests: submit → get_order returns it; cancel → state changes; get_fills returns fills.

## Touches

- `trade_engine/broker_adapter.py` — `get_fills()`, `get_quote()`, `get_account()`, `__init__`
- `trade_engine/market_data.py` (new) — extracted quote functions
- `trade_engine/execution_engine.py` — import from `market_data` instead of defining `_get_quote` locally
- `tests/test_trade_engine.py` — BrokerAdapter contract tests

## Done when

- [ ] `trade_engine/market_data.py` exists and contains quote retrieval functions
- [ ] `broker_adapter.py` imports from `market_data`, not from `execution_engine`
- [ ] `ShadowBrokerAdapter.__init__` accepts `account_id`
- [ ] `get_fills(account_id, since=None)` uses correct SQL params
- [ ] `get_account(account_id)` loads from `trading_accounts`
- [ ] `BrokerAdapterContractTests` mixin passes for `ShadowBrokerAdapter`
- [ ] No circular imports between `broker_adapter` and `execution_engine`
- [ ] All existing tests pass
