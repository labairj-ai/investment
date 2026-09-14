"""TradingPolicy: loads config/trading_policy.json and exposes typed accessors."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_POLICY_DIR = Path(__file__).resolve().parent.parent / "config"
_POLICY_PATH = _POLICY_DIR / "trading_policy.json"


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

    def max_spread_pct(self) -> float:
        return float(self.execution.get("max_spread_pct", 2.0))

    # ── risk ──────────────────────────────────────────────────────────────────
    def max_drawdown_pct(self) -> float:
        return float(self.risk.get("max_drawdown_pct", 10))

    def max_daily_loss_pct(self) -> float:
        return float(self.risk.get("max_daily_loss_pct", 3))

    def expected_broker_account_id(self) -> Optional[str]:
        """Broker account ID that must match broker.get_account_id() at session init (0272).

        None means no binding check — opt-out for shadow/paper accounts without a real broker ID.
        """
        return self.circuit_breakers.get("expected_broker_account_id", None)

    def require_account_binding(self) -> bool:
        """When True, initialization halts if expected_broker_account_id is not configured (0276).

        For live accounts, set require_account_binding=True in circuit_breakers to enforce
        that the operator explicitly configures the expected broker account ID. A policy that
        cannot be loaded at all always halts regardless of this flag.
        """
        return bool(self.circuit_breakers.get("require_account_binding", False))

    def policy_hash(self) -> str:
        # Hash resolved effective policy so env-var substitutions (e.g. ALPACA_PAPER_ACCOUNT_ID)
        # change the hash. _raw_json contains unresolved ${...} placeholders (0323).
        resolved = {
            "policy_version": self.policy_version,
            "account_id": self.account_id,
            "capital": self.capital,
            "equities": self.equities,
            "options": self.options,
            "execution": self.execution,
            "risk": self.risk,
            "circuit_breakers": self.circuit_breakers,
        }
        return hashlib.sha256(json.dumps(resolved, sort_keys=True).encode()).hexdigest()[:12]


def _resolve_env_vars(circuit_breakers: dict) -> dict:
    """Substitute ${ENV_VAR} placeholders in circuit_breakers fields.

    Allows expected_broker_account_id to be configured via env without committing
    the actual account ID to the repo. Returns a copy with substitutions applied.
    """
    cb = dict(circuit_breakers)
    val = cb.get("expected_broker_account_id")
    if isinstance(val, str) and val.startswith("${") and val.endswith("}"):
        env_name = val[2:-1]
        resolved = os.environ.get(env_name) or None
        cb["expected_broker_account_id"] = resolved
    return cb


def load_policy(account_id: str, policy_path: Path | None = None) -> TradingPolicy:
    if policy_path is None:
        per_account = _POLICY_DIR / f"trading_policy_{account_id.lower()}.json"
        path = per_account if per_account.exists() else _POLICY_PATH
    else:
        path = policy_path
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
        circuit_breakers=_resolve_env_vars(data.get("circuit_breakers", {})),
        _raw_json=raw,
    )
