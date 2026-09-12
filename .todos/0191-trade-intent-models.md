# TradingAccount + TradeIntent + Supporting Models

- **ID:** 0191
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0190

## Problem

The system needs formally-typed Python objects for the core trade execution concepts. These are the lingua franca of the entire trade engine: every other module accepts or returns these types. Getting the schema exactly right here prevents ad-hoc dict-passing that was the source of many bugs in the agent layer.

## Proposed approach

Create `trade_engine/models.py` with frozen/validated dataclasses and enums:

```python
# Enums
class AccountMode(str, Enum):
    SHADOW = "shadow"
    PAPER  = "paper"
    LIVE   = "live"

class InstrumentType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"

class Side(str, Enum):
    BUY          = "BUY"
    SELL         = "SELL"
    SELL_TO_OPEN = "SELL_TO_OPEN"
    BUY_TO_CLOSE = "BUY_TO_CLOSE"

class OrderType(str, Enum):
    LIMIT  = "LIMIT"
    MARKET = "MARKET"

class TimeInForce(str, Enum):
    DAY = "DAY"
    GTC = "GTC"

class OrderState(str, Enum):
    PENDING          = "PENDING"
    SUBMITTED        = "SUBMITTED"
    WORKING          = "WORKING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED           = "FILLED"
    CANCELLED        = "CANCELLED"
    REJECTED         = "REJECTED"
    EXPIRED          = "EXPIRED"
    ERROR            = "ERROR"

class IntentStatus(str, Enum):
    PENDING  = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXPIRED  = "EXPIRED"
    FILLED   = "FILLED"

class RuleResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"  # rule not applicable to this intent

# Dataclasses
@dataclass(frozen=True)
class TradingAccount:
    account_id: str
    name: str
    mode: AccountMode
    starting_capital: Decimal
    current_cash: Decimal
    trading_enabled: bool
    policy_version: str
    broker: str | None = None

@dataclass(frozen=True)
class TradeIntent:
    intent_id: str            # UUID
    account_id: str
    recommendation_id: int | None
    agent_run_id: int | None
    instrument_type: InstrumentType
    symbol: str
    side: Side
    quantity: float | None    # shares (equity)
    contracts: int | None     # for options
    option_type: str | None   # 'CALL' | 'PUT'
    strike: float | None
    expiration: str | None    # ISO date
    order_type: OrderType
    limit_price: float
    time_in_force: TimeInForce
    strategy: str
    thesis_version: int | None
    strategy_config_hash: str | None
    valid_until: str          # ISO datetime
    created_at: str           # ISO datetime
    status: IntentStatus = IntentStatus.PENDING

    def is_expired(self) -> bool: ...
    def to_db_dict(self) -> dict: ...

@dataclass(frozen=True)
class RuleCheck:
    rule: str
    result: RuleResult
    limit: float | None = None
    before: float | None = None
    after: float | None = None
    reason: str | None = None

@dataclass(frozen=True)
class RiskDecision:
    decision_id: str        # UUID
    intent_id: str
    decision: str           # 'APPROVED' | 'REJECTED'
    checks: list[RuleCheck]
    evaluated_at: str

@dataclass
class Order:
    order_id: str
    intent_id: str
    account_id: str
    symbol: str
    side: Side
    quantity: float | None
    contracts: int | None
    order_type: OrderType
    limit_price: float
    state: OrderState = OrderState.PENDING
    broker_order_id: str | None = None
    submitted_at: str | None = None
    updated_at: str | None = None
    fill_qty: float = 0.0
    fill_cash: float = 0.0

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
```

All models must be JSON-serializable via a `to_dict()` / `from_dict()` round-trip.

## Touches

- `trade_engine/__init__.py` — new package
- `trade_engine/models.py` — all models above

## Done when

- [ ] All enums and dataclasses defined and importable from `trade_engine.models`
- [ ] `TradeIntent.is_expired()` returns True when `valid_until` < now
- [ ] `TradeIntent.to_db_dict()` produces flat dict matching `trade_intents` table columns
- [ ] `Order` state transition is validated (only legal transitions allowed)
- [ ] All models round-trip through `to_dict()` / `from_dict()` without loss
- [ ] Unit tests for expiry, serialization, and illegal state transitions
