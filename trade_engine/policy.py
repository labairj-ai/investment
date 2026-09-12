"""TradingPolicy: loads config/trading_policy.json and exposes typed accessors."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

_POLICY_PATH = Path(__file__).resolve().parent.parent / "config" / "trading_policy.json"


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
    _raw_json: str = ""

    # ── circuit breakers ──────────────────────────────────────────────────────
    def trading_enabled(self) -> bool:
        return bool(self.circuit_breakers.get("trading_enabled", True))

    def halt_on_data_stale_minutes(self) -> int:
        return int(self.circuit_breakers.get("halt_on_data_stale_minutes", 60))

    # ── capital ───────────────────────────────────────────────────────────────
    def starting_capital(self) -> float:
        return float(self.capital.get("starting_capital", 10000))

    def min_cash_pct(self) -> float:
        return float(self.capital.get("minimum_cash_pct", 10))

    def min_cash_abs(self) -> float:
        return float(self.capital.get("minimum_cash_abs", 500))

    # ── equities ──────────────────────────────────────────────────────────────
    def buy_allowed(self) -> bool:
        return bool(self.equities.get("buy_allowed", True))

    def sell_allowed(self) -> bool:
        return bool(self.equities.get("sell_allowed", True))

    def shorting_allowed(self) -> bool:
        return bool(self.equities.get("shorting_allowed", False))

    def max_single_position_pct(self) -> float:
        return float(self.equities.get("max_single_position_pct", 10))

    def max_new_position_pct(self) -> float:
        return float(self.equities.get("max_new_position_pct", 5))

    # ── options ───────────────────────────────────────────────────────────────
    def covered_calls_allowed(self) -> bool:
        return bool(self.options.get("covered_calls_allowed", True))

    def naked_options_allowed(self) -> bool:
        return bool(self.options.get("naked_options_allowed", False))

    def max_contracts_per_symbol(self) -> int:
        return int(self.options.get("max_contracts_per_symbol", 1))

    # ── execution ─────────────────────────────────────────────────────────────
    def min_limit_price(self) -> float:
        return float(self.execution.get("min_limit_price", 0.01))

    def market_orders_allowed(self) -> bool:
        return bool(self.execution.get("market_orders_allowed", False))

    def max_orders_per_day(self) -> int:
        return int(self.execution.get("max_orders_per_day", 5))

    def max_daily_notional_pct(self) -> float:
        return float(self.execution.get("max_daily_notional_pct", 20))

    def max_slippage_pct(self) -> float:
        return float(self.execution.get("max_slippage_pct", 1.0))

    # ── risk ──────────────────────────────────────────────────────────────────
    def max_drawdown_pct(self) -> float:
        return float(self.risk.get("max_drawdown_pct", 10))

    def max_daily_loss_pct(self) -> float:
        return float(self.risk.get("max_daily_loss_pct", 3))

    def policy_hash(self) -> str:
        return hashlib.sha256(self._raw_json.encode()).hexdigest()[:12]


def load_policy(account_id: str, policy_path: Path | None = None) -> TradingPolicy:
    path = policy_path or _POLICY_PATH
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    if data.get("account_id") != account_id:
        raise ValueError(
            f"Policy file account_id={data.get('account_id')!r} "
            f"does not match requested account_id={account_id!r}"
        )
    return TradingPolicy(
        policy_version=data.get("policy_version", "1.0"),
        account_id=data["account_id"],
        capital=data.get("capital", {}),
        equities=data.get("equities", {}),
        options=data.get("options", {}),
        execution=data.get("execution", {}),
        risk=data.get("risk", {}),
        circuit_breakers=data.get("circuit_breakers", {}),
        _raw_json=raw,
    )
