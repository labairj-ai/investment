"""Domain models for the trade execution engine."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class AccountMode(str, Enum):
    SHADOW = "shadow"
    PAPER = "paper"
    LIVE = "live"


class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    SELL_TO_OPEN = "SELL_TO_OPEN"
    BUY_TO_CLOSE = "BUY_TO_CLOSE"


class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"


class TimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"


class OrderState(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    WORKING = "WORKING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    ERROR = "ERROR"


_VALID_TRANSITIONS: dict[OrderState, set[OrderState]] = {
    OrderState.PENDING: {OrderState.SUBMITTED},
    OrderState.SUBMITTED: {OrderState.WORKING, OrderState.REJECTED},
    OrderState.WORKING: {
        OrderState.FILLED,
        OrderState.PARTIALLY_FILLED,
        OrderState.CANCELLED,
        OrderState.EXPIRED,
        OrderState.ERROR,
    },
    OrderState.PARTIALLY_FILLED: {OrderState.FILLED, OrderState.CANCELLED},
    OrderState.FILLED: set(),
    OrderState.CANCELLED: set(),
    OrderState.REJECTED: set(),
    OrderState.EXPIRED: set(),
    OrderState.ERROR: set(),
}


class IntentStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FILLED = "FILLED"


class RuleResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


class InvalidStateTransition(Exception):
    pass


@dataclass(frozen=True)
class TradingAccount:
    account_id: str
    name: str
    mode: AccountMode
    starting_capital: float
    current_cash: float
    trading_enabled: bool
    policy_version: str
    broker: Optional[str] = None

    def nav(self, position_value: float = 0.0) -> float:
        return self.current_cash + position_value

    @classmethod
    def from_db_row(cls, row) -> "TradingAccount":
        return cls(
            account_id=row["account_id"],
            name=row["name"] or "",
            mode=AccountMode(row["mode"]),
            starting_capital=float(row["starting_capital"] or 0),
            current_cash=float(row["current_cash"] or 0),
            trading_enabled=bool(row["trading_enabled"]),
            policy_version=row["policy_version"] or "1.0",
            broker=row["broker"],
        )


@dataclass(frozen=True)
class TradeIntent:
    intent_id: str
    account_id: str
    recommendation_id: Optional[int]
    agent_run_id: Optional[int]
    instrument_type: InstrumentType
    symbol: str
    side: Side
    quantity: Optional[float]
    contracts: Optional[int]
    option_type: Optional[str]
    strike: Optional[float]
    expiration: Optional[str]
    order_type: OrderType
    limit_price: float
    time_in_force: TimeInForce
    strategy: str
    thesis_version: Optional[int]
    strategy_config_hash: Optional[str]
    valid_until: str
    created_at: str
    status: IntentStatus = IntentStatus.PENDING

    def is_expired(self) -> bool:
        try:
            vu = datetime.fromisoformat(self.valid_until.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > vu
        except Exception:
            return False

    def notional(self) -> float:
        qty = self.quantity or 0.0
        return qty * self.limit_price

    def to_db_dict(self) -> dict:
        return {
            "intent_id": self.intent_id,
            "account_id": self.account_id,
            "recommendation_id": self.recommendation_id,
            "agent_run_id": self.agent_run_id,
            "instrument_type": self.instrument_type.value,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "contracts": self.contracts,
            "option_type": self.option_type,
            "strike": self.strike,
            "expiration": self.expiration,
            "order_type": self.order_type.value,
            "limit_price": self.limit_price,
            "time_in_force": self.time_in_force.value,
            "strategy": self.strategy,
            "thesis_version": self.thesis_version,
            "strategy_config_hash": self.strategy_config_hash,
            "valid_until": self.valid_until,
            "created_at": self.created_at,
            "status": self.status.value,
        }

    @classmethod
    def from_db_row(cls, row) -> "TradeIntent":
        return cls(
            intent_id=row["intent_id"],
            account_id=row["account_id"],
            recommendation_id=row["recommendation_id"],
            agent_run_id=row["agent_run_id"],
            instrument_type=InstrumentType(row["instrument_type"]),
            symbol=row["symbol"],
            side=Side(row["side"]),
            quantity=row["quantity"],
            contracts=row["contracts"],
            option_type=row["option_type"],
            strike=row["strike"],
            expiration=row["expiration"],
            order_type=OrderType(row["order_type"]),
            limit_price=float(row["limit_price"] or 0),
            time_in_force=TimeInForce(row["time_in_force"]),
            strategy=row["strategy"] or "",
            thesis_version=row["thesis_version"],
            strategy_config_hash=row["strategy_config_hash"],
            valid_until=row["valid_until"],
            created_at=row["created_at"],
            status=IntentStatus(row["status"]),
        )


@dataclass(frozen=True)
class RuleCheck:
    rule: str
    result: RuleResult
    limit: Optional[float] = None
    before: Optional[float] = None
    after: Optional[float] = None
    reason: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "rule": self.rule,
            "result": self.result.value,
            "limit": self.limit,
            "before": self.before,
            "after": self.after,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RiskDecision:
    decision_id: str
    intent_id: str
    decision: str
    checks: list
    evaluated_at: str

    def to_dict(self) -> dict:
        return {
            "decision_id": self.decision_id,
            "intent_id": self.intent_id,
            "decision": self.decision,
            "checks": [c.to_dict() for c in self.checks],
            "evaluated_at": self.evaluated_at,
        }


@dataclass
class Order:
    order_id: str
    intent_id: str
    account_id: str
    symbol: str
    side: Side
    quantity: Optional[float]
    contracts: Optional[int]
    order_type: OrderType
    limit_price: float
    state: OrderState = OrderState.PENDING
    time_in_force: TimeInForce = TimeInForce.DAY
    broker_order_id: Optional[str] = None
    submitted_at: Optional[str] = None
    updated_at: Optional[str] = None
    fill_qty: float = 0.0
    fill_cash: float = 0.0

    def transition(self, new_state: OrderState) -> None:
        allowed = _VALID_TRANSITIONS.get(self.state, set())
        if new_state not in allowed:
            raise InvalidStateTransition(
                f"{self.state.value} → {new_state.value} is not a valid order state transition"
            )
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def to_db_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "intent_id": self.intent_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "contracts": self.contracts,
            "order_type": self.order_type.value,
            "limit_price": self.limit_price,
            "state": self.state.value,
            "time_in_force": self.time_in_force.value,
            "broker_order_id": self.broker_order_id,
            "submitted_at": self.submitted_at,
            "updated_at": self.updated_at,
            "fill_qty": self.fill_qty,
            "fill_cash": self.fill_cash,
        }

    @classmethod
    def from_db_row(cls, row) -> "Order":
        tif_val = row["time_in_force"] if "time_in_force" in row.keys() else "DAY"
        return cls(
            order_id=row["order_id"],
            intent_id=row["intent_id"],
            account_id=row["account_id"],
            symbol=row["symbol"],
            side=Side(row["side"]),
            quantity=row["quantity"],
            contracts=row["contracts"],
            order_type=OrderType(row["order_type"]),
            limit_price=float(row["limit_price"] or 0),
            state=OrderState(row["state"]),
            time_in_force=TimeInForce(tif_val or "DAY"),
            broker_order_id=row["broker_order_id"],
            submitted_at=row["submitted_at"],
            updated_at=row["updated_at"],
            fill_qty=float(row["fill_qty"] or 0),
            fill_cash=float(row["fill_cash"] or 0),
        )


@dataclass(frozen=True)
class Fill:
    fill_id: str
    order_id: str
    account_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
    fill_source: str
    filled_at: str

    def cash_impact(self) -> float:
        """Positive = cash received (sell); negative = cash paid (buy)."""
        sign = 1.0 if self.side in (Side.SELL, Side.SELL_TO_OPEN) else -1.0
        return sign * (self.qty * self.price) - self.fee

    def to_dict(self) -> dict:
        return {
            "fill_id": self.fill_id,
            "order_id": self.order_id,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "side": self.side.value,
            "qty": self.qty,
            "price": self.price,
            "fee": self.fee,
            "fill_source": self.fill_source,
            "filled_at": self.filled_at,
        }

    @classmethod
    def from_db_row(cls, row) -> "Fill":
        return cls(
            fill_id=row["fill_id"],
            order_id=row["order_id"],
            account_id=row["account_id"],
            symbol=row["symbol"],
            side=Side(row["side"]),
            qty=float(row["qty"] or 0),
            price=float(row["price"] or 0),
            fee=float(row["fee"] or 0),
            fill_source=row["fill_source"] or "shadow",
            filled_at=row["filled_at"],
        )


@dataclass
class ExecutionResult:
    intent_id: str
    decision: str
    order_id: Optional[str]
    fill: Optional[Fill]
    risk_decision: RiskDecision
    elapsed_ms: int

    def to_dict(self) -> dict:
        return {
            "intent_id": self.intent_id,
            "decision": self.decision,
            "order_id": self.order_id,
            "fill": self.fill.to_dict() if self.fill else None,
            "risk_decision": self.risk_decision.to_dict(),
            "elapsed_ms": self.elapsed_ms,
        }
