"""BrokerAdapter: normalized interface for all broker integrations (0237, 0238).

ExecutionEngine accepts a BrokerAdapter and never instantiates ShadowBroker directly.
Shadow mode is the reference implementation. Paper/live adapters translate broker-native
objects to the normalized types in broker_types.py before returning them.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .broker_types import BrokerAccountState, BrokerFill, BrokerOrder, BrokerPosition, BrokerQuote
from .models import Fill, Order, TradeIntent, TradingAccount


class BrokerAdapter(ABC):
    """Broker-agnostic interface for order management, market data, and account state."""

    # Whether this adapter requires market_timestamp on quotes for safe execution (0235).
    # Shadow: False (yfinance retrieved_at fallback is acceptable).
    # Paper/live: True (broker must supply exchange observation time).
    requires_market_timestamp: bool = False

    @abstractmethod
    def get_broker_account(self, account_id: str) -> BrokerAccountState: ...

    @abstractmethod
    def get_positions(self, account_id: str) -> list[BrokerPosition]: ...

    @abstractmethod
    def get_open_orders(self, account_id: str) -> list[BrokerOrder]: ...

    @abstractmethod
    def get_quote(self, symbol: str) -> Optional[BrokerQuote]: ...

    @abstractmethod
    def submit_order(self, intent: TradeIntent) -> Order: ...

    @abstractmethod
    def cancel_order(self, order_id: str, reason: str = "USER_REQUESTED") -> Order: ...

    @abstractmethod
    def attempt_fill(self, order: Order, quote: BrokerQuote) -> Optional[Fill]: ...

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[Order]: ...

    @abstractmethod
    def get_fills(self, account_id: str, since: Optional[str] = None) -> list[BrokerFill]: ...

    # Legacy helper — still used by some callers before full migration
    def get_account(self, account_id: str) -> TradingAccount:
        raise NotImplementedError


class ShadowBrokerAdapter(BrokerAdapter):
    """Shadow (SQLite-backed) implementation of BrokerAdapter (0238).

    Wraps ShadowBroker for order/fill operations. Translates shadow types to the
    normalized broker_types where needed. ShadowBrokerAdapter is the reference
    implementation that all new adapters must match via the contract test suite (0241).
    """

    requires_market_timestamp = False  # yfinance retrieved_at fallback is fine for shadow

    def __init__(self, conn, account_id: str) -> None:
        from .shadow_broker import ShadowBroker
        self._broker = ShadowBroker(conn)
        self._conn = conn
        self.account_id = account_id

    # ── Account ───────────────────────────────────────────────────────────────

    def get_broker_account(self, account_id: str) -> BrokerAccountState:
        from .risk_engine import _open_buy_notional
        row = self._conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Account {account_id!r} not found")
        cash = float(row["current_cash"] or 0)
        pos_rows = self._conn.execute(
            "SELECT qty, avg_cost, market_value FROM position_snapshots WHERE account_id=?",
            (account_id,),
        ).fetchall()
        gross = sum(
            float(r["market_value"]) if r["market_value"] is not None
            else float(r["qty"] or 0) * float(r["avg_cost"] or 0)
            for r in pos_rows
        )
        nav = cash + gross
        reserved = _open_buy_notional(account_id, self._conn)
        return BrokerAccountState(
            account_id=account_id,
            cash=cash,
            nav=nav,
            buying_power=max(0.0, cash - reserved),
        )

    def get_account(self, account_id: str) -> TradingAccount:
        row = self._conn.execute(
            "SELECT * FROM trading_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Account {account_id!r} not found")
        return TradingAccount.from_db_row(row)

    # ── Positions ─────────────────────────────────────────────────────────────

    def get_positions(self, account_id: str) -> list[BrokerPosition]:
        rows = self._conn.execute(
            "SELECT symbol, qty, avg_cost, instrument_type, market_price, market_value "
            "FROM position_snapshots WHERE account_id=?",
            (account_id,),
        ).fetchall()
        return [
            BrokerPosition(
                symbol=r["symbol"],
                qty=float(r["qty"] or 0),
                avg_cost=float(r["avg_cost"] or 0),
                instrument_type=r["instrument_type"] or "EQUITY",
                market_price=float(r["market_price"]) if r["market_price"] is not None else None,
                market_value=float(r["market_value"]) if r["market_value"] is not None else None,
            )
            for r in rows
        ]

    # ── Orders ────────────────────────────────────────────────────────────────

    def get_open_orders(self, account_id: str) -> list[BrokerOrder]:
        rows = self._conn.execute(
            "SELECT order_id, symbol, side, quantity, fill_qty, state, limit_price "
            "FROM orders WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')",
            (account_id,),
        ).fetchall()
        return [
            BrokerOrder(
                broker_order_id=r["order_id"],
                symbol=r["symbol"],
                side=r["side"],
                quantity=float(r["quantity"] or 0),
                fill_qty=float(r["fill_qty"] or 0),
                state=r["state"],
                limit_price=float(r["limit_price"]) if r["limit_price"] is not None else None,
                local_order_id=r["order_id"],
            )
            for r in rows
        ]

    def submit_order(self, intent: TradeIntent) -> Order:
        return self._broker.submit_order(intent)

    def cancel_order(self, order_id: str, reason: str = "USER_REQUESTED") -> Order:
        return self._broker.cancel_order(order_id, reason=reason)

    def get_order(self, order_id: str) -> Optional[Order]:
        return self._broker.get_order(order_id)

    # ── Fills ─────────────────────────────────────────────────────────────────

    def attempt_fill(self, order: Order, quote: BrokerQuote) -> Optional[Fill]:
        from .shadow_broker import Quote as ShadowQuote
        # Translate BrokerQuote → ShadowBroker's Quote for internal fill logic
        shadow_q = ShadowQuote(
            bid=quote.bid,
            ask=quote.ask,
            timestamp="",
            market_timestamp=quote.market_timestamp,
            retrieved_at=quote.retrieved_at,
            source=quote.source,
        )
        return self._broker.attempt_fill(order, shadow_q)

    def get_fills(self, account_id: str, since: Optional[str] = None) -> list[BrokerFill]:
        if since:
            rows = self._conn.execute(
                "SELECT * FROM fills WHERE account_id=? AND filled_at >= ?",
                (account_id, since),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM fills WHERE account_id=?", (account_id,)
            ).fetchall()
        return [
            BrokerFill(
                broker_fill_id=r["fill_id"],
                broker_order_id=r["order_id"],
                symbol=r["symbol"],
                side=r["side"],
                qty=float(r["qty"] or 0),
                price=float(r["price"] or 0),
                filled_at=r["filled_at"],
                fee=float(r["fee"] or 0),
                local_order_id=r["order_id"],
                account_id=r["account_id"],
            )
            for r in rows
        ]

    # ── Quotes ────────────────────────────────────────────────────────────────

    def get_quote(self, symbol: str) -> Optional[BrokerQuote]:
        from .market_data import _get_executable_quote
        q = _get_executable_quote(symbol)
        if not q:
            return None
        return BrokerQuote(
            bid=q.bid,
            ask=q.ask,
            symbol=symbol,
            market_timestamp=q.market_timestamp,
            retrieved_at=q.retrieved_at,
            source=q.source,
        )
