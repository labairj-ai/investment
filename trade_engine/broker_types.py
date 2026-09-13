"""Broker-neutral domain types for the adapter layer (0237).

Every broker adapter translates its native objects to these types.
No IBKR, Alpaca, or shadow-specific schemas should leak past an adapter boundary.
"""
from __future__ import annotations

from enum import Enum
from typing import NamedTuple, Optional


class BrokerOrderState(str, Enum):
    """Normalized order states across all adapters (0250).

    Adapters map broker-native strings to these at the boundary.
    Shadow mode uses these directly; IBKR/Alpaca adapters translate on ingestion.
    """
    PENDING = "PENDING"
    WORKING = "WORKING"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"
    ERROR = "ERROR"


class BrokerFillStatus(str, Enum):
    """Fill confirmation status from the broker (0250)."""
    CONFIRMED = "CONFIRMED"
    PENDING = "PENDING"
    REJECTED = "REJECTED"


class BrokerQuote(NamedTuple):
    """Exchange-observed bid/ask with provenance timestamps."""
    bid: float
    ask: float
    symbol: str = ""
    market_timestamp: Optional[str] = None   # when the exchange last published this quote
    retrieved_at: Optional[str] = None       # when we fetched it from the data source
    source: str = "unknown"


class BrokerPosition(NamedTuple):
    """Broker-reported position for a single symbol."""
    symbol: str
    qty: float
    avg_cost: float
    instrument_type: str = "EQUITY"
    market_price: Optional[float] = None
    market_value: Optional[float] = None


class BrokerOrder(NamedTuple):
    """Broker-reported order state (read from broker, not local DB)."""
    broker_order_id: str
    symbol: str
    side: str
    quantity: float
    fill_qty: float
    state: str
    limit_price: Optional[float] = None
    local_order_id: Optional[str] = None    # maps back to orders.order_id
    client_order_id: Optional[str] = None   # durable idempotency key (0247)


class BrokerFill(NamedTuple):
    """A single execution reported by the broker."""
    broker_fill_id: str
    broker_order_id: str
    symbol: str
    side: str
    qty: float
    price: float
    filled_at: str
    fee: float = 0.0
    local_order_id: Optional[str] = None
    account_id: Optional[str] = None


class BrokerAccountState(NamedTuple):
    """Account-level financials as reported by the broker."""
    account_id: str
    cash: float
    nav: float
    buying_power: float


class BrokerOrderEvent(NamedTuple):
    """An order lifecycle event from the broker (fill, cancel, expiry) (0248).

    The execution engine drives state machine transitions from these events rather than
    from the return value of attempt_fill(). Real adapters produce events asynchronously;
    shadow adapts synchronously for testing.
    """
    event_type: str           # FILLED | PARTIALLY_FILLED | CANCELLED | EXPIRED
    broker_order_id: str
    local_order_id: Optional[str] = None
    fill_qty: float = 0.0
    fill_price: float = 0.0
    filled_at: Optional[str] = None
    fee: float = 0.0
    broker_fill_id: Optional[str] = None   # canonical fill ID for deduplication (0256)
