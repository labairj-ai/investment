"""Broker-neutral domain types for the adapter layer (0237).

Every broker adapter translates its native objects to these types.
No IBKR, Alpaca, or shadow-specific schemas should leak past an adapter boundary.
"""
from __future__ import annotations

from typing import NamedTuple, Optional


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
