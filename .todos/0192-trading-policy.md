# TradingPolicy: config/trading_policy.json + Policy Loader

- **ID:** 0192
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0191

## Problem

`strategy.json` answers "what investments do we prefer?" — it must not also answer "what is the machine allowed to do?" Mixing these creates a future footgun: strategy tuning should not require touching the same file as execution authorization.

`trading_policy.json` is the authoritative source for what the execution system may do. It is read-only at runtime. The LLM never sees it directly and cannot modify it. Policy version is embedded in every TradeIntent and RiskDecision for audit.

## Proposed approach

**`config/trading_policy.json`** (initial values for AGENTIC_SHADOW_01 — actual numbers TBD before live):
```json
{
  "policy_version": "1.0",
  "account_id": "AGENTIC_SHADOW_01",

  "capital": {
    "starting_capital": 10000,
    "minimum_cash_pct": 10,
    "minimum_cash_abs": 500
  },

  "equities": {
    "buy_allowed": true,
    "sell_allowed": true,
    "shorting_allowed": false,
    "max_single_position_pct": 10,
    "max_new_position_pct": 5
  },

  "options": {
    "covered_calls_allowed": true,
    "cash_secured_puts_allowed": false,
    "naked_options_allowed": false,
    "max_contracts_per_symbol": 1
  },

  "execution": {
    "market_orders_allowed": false,
    "max_orders_per_day": 5,
    "max_daily_notional_pct": 20,
    "max_slippage_pct": 1.0,
    "min_limit_price": 0.01
  },

  "risk": {
    "max_drawdown_pct": 10,
    "max_daily_loss_pct": 3,
    "max_weekly_loss_pct": 7
  },

  "circuit_breakers": {
    "trading_enabled": true,
    "halt_on_position_mismatch": true,
    "halt_on_data_stale_minutes": 60,
    "halt_on_daily_loss_pct": 3
  }
}
```

**`trade_engine/policy.py`**:
```python
@dataclass(frozen=True)
class TradingPolicy:
    policy_version: str
    account_id: str
    capital: dict
    equities: dict
    options: dict
    execution: dict
    risk: dict
    circuit_breakers: dict

    def buy_allowed(self) -> bool: ...
    def sell_allowed(self) -> bool: ...
    def market_orders_allowed(self) -> bool: ...
    def max_single_position_pct(self) -> float: ...
    def min_cash_pct(self) -> float: ...
    def max_daily_notional_pct(self) -> float: ...
    def max_daily_loss_pct(self) -> float: ...
    def trading_enabled(self) -> bool: ...
    # etc. — typed accessors for every field the risk engine queries

def load_policy(account_id: str) -> TradingPolicy: ...
```

The loader reads `config/trading_policy.json`, validates `account_id` matches, and returns a frozen `TradingPolicy`. A `policy_hash()` method returns the 12-char SHA256 of the file content for embedding in intents (mirrors `strategy_config_hash` pattern already used in the codebase).

## Touches

- `config/trading_policy.json` — new file
- `trade_engine/policy.py` — loader + TradingPolicy dataclass

## Done when

- [ ] `config/trading_policy.json` exists with all sections above
- [ ] `load_policy("AGENTIC_SHADOW_01")` returns a typed `TradingPolicy`
- [ ] `TradingPolicy.trading_enabled()` returns False when circuit_breakers.trading_enabled=false
- [ ] `policy_hash()` returns consistent 12-char hash matching file content
- [ ] Loading policy for unknown account_id raises `ValueError`
- [ ] Tests verify all typed accessors against the JSON values
