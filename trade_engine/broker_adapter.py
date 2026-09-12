"""BrokerAdapter: abstract base class for broker integrations (0218 — B1 design stub).

This file defines the interface that ShadowBroker and future paper/live broker
adapters must implement. ExecutionEngine will accept a BrokerAdapter instead of
constructing ShadowBroker directly (B1 milestone).

Do not add IBKR/Alpaca implementation here — that is B1 scope.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .models import Fill, Order, TradeIntent, TradingAccount
from .shadow_broker import Quote


class BrokerAdapter(ABC):
    """Broker-agnostic interface for order management and market data."""

    @abstractmethod
    def get_account(self) -> TradingAccount: ...

    @abstractmethod
    def get_positions(self, account_id: str) -> list: ...

    @abstractmethod
    def get_open_orders(self, account_id: str) -> list[Order]: ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[Quote]: ...

    @abstractmethod
    def submit_order(self, intent: TradeIntent) -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> Order: ...

    @abstractmethod
    def replace_order(self, order_id: str, changes: dict) -> Order: ...

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]: ...

    @abstractmethod
    def get_fills(self, since: Optional[str] = None) -> list[Fill]: ...


class ShadowBrokerAdapter(BrokerAdapter):
    """Thin wrapper mapping BrokerAdapter contract to ShadowBroker (B1 bridge stub).

    Full implementation lives in shadow_broker.ShadowBroker. This adapter exists
    so ExecutionEngine can program against BrokerAdapter without knowing the
    concrete type — enabling parallel paper/live execution in the future.
    """

    def __init__(self, conn) -> None:
        import sqlite3
        from .shadow_broker import ShadowBroker
        self._broker = ShadowBroker(conn)
        self._conn = conn

    def get_account(self) -> TradingAccount:
        raise NotImplementedError("B1: load from trading_accounts via account_id")

    def get_positions(self, account_id: str) -> list:
        return list(self._broker.get_positions(account_id).items())

    def get_open_orders(self, account_id: str) -> list[Order]:
        rows = self._conn.execute(
            "SELECT * FROM orders WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')",
            (account_id,),
        ).fetchall()
        return [Order.from_db_row(r) for r in rows]

    def get_quote(self, symbol: str) -> Optional[Quote]:
        from .execution_engine import _get_quote
        return _get_quote(symbol)

    def submit_order(self, intent: TradeIntent) -> Order:
        return self._broker.submit_order(intent)

    def cancel_order(self, order_id: str) -> Order:
        return self._broker.cancel_order(order_id)

    def replace_order(self, order_id: str, changes: dict) -> Order:
        raise NotImplementedError("B1: order replacement not implemented for shadow")

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._broker.get_order(order_id)

    def get_fills(self, since: Optional[str] = None) -> list[Fill]:
        if since:
            rows = self._conn.execute(
                "SELECT * FROM fills WHERE account_id=? AND filled_at >= ?",
                (self._conn, since),
            ).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM fills").fetchall()
        return [Fill.from_db_row(r) for r in rows]
