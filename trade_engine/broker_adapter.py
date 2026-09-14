"""BrokerAdapter: normalized interface for all broker integrations (0237, 0238).

ExecutionEngine accepts a BrokerAdapter and never instantiates ShadowBroker directly.
Shadow mode is the reference implementation. Paper/live adapters translate broker-native
objects to the normalized types in broker_types.py before returning them.
"""
from __future__ import annotations

import datetime
from abc import ABC, abstractmethod
from typing import Optional

from .broker_types import BrokerAccountState, BrokerCancelAck, BrokerFill, BrokerOrder, BrokerOrderAck, BrokerOrderEvent, BrokerPosition, BrokerQuote
from .models import Fill, Order, TradeIntent, TradingAccount


def _shadow_quote_fresh(quote: BrokerQuote, stale_minutes: int) -> bool:
    """Return True when the quote is recent enough to trigger a simulated fill (0259)."""
    now = datetime.datetime.now(datetime.timezone.utc).timestamp()
    if quote.market_timestamp:
        try:
            ts = datetime.datetime.fromisoformat(quote.market_timestamp).timestamp()
            return (now - ts) / 60 <= stale_minutes
        except Exception:
            pass
    if quote.retrieved_at:
        try:
            ts = datetime.datetime.fromisoformat(quote.retrieved_at).timestamp()
            return (now - ts) / 60 <= stale_minutes
        except Exception:
            pass
    return False


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
    def submit_order(self, intent: TradeIntent, client_order_id: Optional[str] = None) -> BrokerOrderAck: ...

    @abstractmethod
    def cancel_order(self, order_id: str, reason: str = "USER_REQUESTED") -> BrokerCancelAck:
        """Cancel an order by broker-native order ID; return normalized cancel confirmation (0275)."""
        ...

    @abstractmethod
    def poll_order_events(
        self, account_id: str, quote: Optional[BrokerQuote] = None
    ) -> list[BrokerOrderEvent]: ...
    """Return order lifecycle events since last poll (fills, cancels, expiries) (0248).

    Shadow: simulates synchronously using the quote to decide fill/expire.
    Paper/live: polls broker API for state changes since last call.
    """

    @abstractmethod
    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        """Return the broker's normalized view of an order by broker-native ID (0275).

        Never returns the internal Order domain model; the engine layer owns that mapping.
        Returns None when the broker has no record of this order ID.
        """
        ...

    @abstractmethod
    def get_fills(self, account_id: str, since: Optional[str] = None) -> list[BrokerFill]: ...

    @abstractmethod
    def get_fills_for_order(self, broker_order_id: str) -> list[BrokerFill]:
        """Return all fills the broker has recorded for a specific order (0273).

        Called in three contexts with distinct empty-return semantics (0278, 0282):
        - After a FILLED ACK: empty return raises BrokerSettlementIndeterminate.
        - After a PARTIALLY_FILLED ACK: empty return raises BrokerSettlementIndeterminate.
        - During PENDING_SUBMIT crash-recovery (reconciliation section 3c): empty return
          appends a RECONCILIATION_UNAVAILABLE discrepancy that blocks new submissions.
        Never called with a fabricated fill ID; callers must use authoritative IDs (0283).
        Raises on transient connectivity errors; caller interprets the exception as
        BrokerSettlementIndeterminate or RECONCILIATION_UNAVAILABLE depending on context.
        """
        ...

    @abstractmethod
    def find_order_by_client_order_id(self, client_order_id: str) -> Optional[BrokerOrder]:
        """Return the broker's view of an order by its client_order_id, or None if not known (0270).

        Returns None when the broker has no record of an order with this client_order_id.
        Raise on transient connectivity errors so callers can distinguish "not found" from "unknown".
        """
        ...

    @abstractmethod
    def get_account_id(self) -> str:
        """Return the broker's canonical account identifier for this session (0272).

        Used during initialization to verify that credentials connect to the expected account.
        Raises on connectivity failure.
        """
        ...

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
            "SELECT order_id, broker_order_id, symbol, side, quantity, fill_qty, state, limit_price, client_order_id "
            "FROM orders WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')",
            (account_id,),
        ).fetchall()
        return [
            BrokerOrder(
                broker_order_id=r["broker_order_id"] or r["order_id"],  # use actual broker ID (0268)
                symbol=r["symbol"],
                side=r["side"],
                quantity=float(r["quantity"] or 0),
                fill_qty=float(r["fill_qty"] or 0),
                state=r["state"],
                limit_price=float(r["limit_price"]) if r["limit_price"] is not None else None,
                local_order_id=r["order_id"],
                client_order_id=r["client_order_id"],
            )
            for r in rows
        ]

    def submit_order(self, intent: TradeIntent, client_order_id: Optional[str] = None) -> BrokerOrderAck:
        order = self._broker.submit_order(intent)
        if client_order_id and order:
            # Persist client_order_id durably so reconciliation can match after a crash (0247)
            self._conn.execute(
                "UPDATE orders SET client_order_id=? WHERE order_id=?",
                (client_order_id, order.order_id),
            )
            self._conn.commit()
        return BrokerOrderAck(
            broker_order_id=order.order_id,
            client_order_id=client_order_id,
            normalized_state=order.state.value if order.state else "WORKING",
            accepted_at=order.submitted_at,
            raw_status=order.state.value if order.state else None,
        )

    def cancel_order(self, order_id: str, reason: str = "USER_REQUESTED") -> BrokerCancelAck:
        self._broker.cancel_order(order_id, reason=reason)
        row = self._conn.execute(
            "SELECT broker_order_id, state FROM orders WHERE order_id=?", (order_id,)
        ).fetchone()
        state = row["state"] if row else None
        return BrokerCancelAck(
            broker_order_id=order_id,
            accepted=state == "CANCELLED",
            normalized_state=state,
            raw_status=state,
        )

    def get_order(self, order_id: str) -> Optional[BrokerOrder]:
        """Return broker-normalized order view; never leaks internal Order model (0275).

        Looks up by broker_order_id first (the caller passes a broker-native ID), then
        falls back to order_id so both regular and reconciliation-imported orders are found.
        """
        row = self._conn.execute(
            "SELECT order_id, broker_order_id, symbol, side, quantity, fill_qty, state, limit_price, client_order_id "
            "FROM orders WHERE broker_order_id=? OR order_id=? LIMIT 1",
            (order_id, order_id),
        ).fetchone()
        if row is None:
            return None
        return BrokerOrder(
            broker_order_id=row["broker_order_id"] or row["order_id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=float(row["quantity"] or 0),
            fill_qty=float(row["fill_qty"] or 0),
            state=row["state"],
            limit_price=float(row["limit_price"]) if row["limit_price"] is not None else None,
            local_order_id=row["order_id"],
            client_order_id=row["client_order_id"],
        )

    def get_fills_for_order(self, broker_order_id: str) -> list[BrokerFill]:
        """Return fills recorded in local DB for this order (shadow: broker == local) (0273)."""
        rows = self._conn.execute(
            "SELECT * FROM fills WHERE order_id=?", (broker_order_id,)
        ).fetchall()
        return [
            BrokerFill(
                broker_fill_id=r["fill_id"],
                broker_order_id=broker_order_id,
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

    def find_order_by_client_order_id(self, client_order_id: str) -> Optional[BrokerOrder]:
        """Return broker's view of order with this client_order_id, including terminal states (0270, 0274).

        Excludes PENDING_SUBMIT (local-only state; a real broker never reports this).
        Includes terminal states (FILLED/CANCELLED/REJECTED/EXPIRED) so crash-restart recovery
        can correctly map broker-terminal → local-terminal rather than → WORKING (0274).
        """
        row = self._conn.execute(
            "SELECT order_id, broker_order_id, symbol, side, quantity, fill_qty, state, limit_price, client_order_id "
            "FROM orders WHERE client_order_id=? AND state != 'PENDING_SUBMIT' ORDER BY submitted_at DESC LIMIT 1",
            (client_order_id,),
        ).fetchone()
        if row is None:
            return None
        return BrokerOrder(
            broker_order_id=row["broker_order_id"] or row["order_id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=float(row["quantity"] or 0),
            fill_qty=float(row["fill_qty"] or 0),
            state=row["state"],
            limit_price=float(row["limit_price"]) if row["limit_price"] is not None else None,
            local_order_id=row["order_id"],
            client_order_id=client_order_id,
        )

    def get_account_id(self) -> str:
        """Return account_id this adapter was initialized for (0272)."""
        return self.account_id

    # ── Fills ─────────────────────────────────────────────────────────────────

    def attempt_fill(self, broker_order_or_order, quote: BrokerQuote) -> Optional[Fill]:
        """Shadow simulation helper; delegates to ShadowBroker.attempt_fill (0248, 0275).

        Accepts either a BrokerOrder (from get_order()) or an internal Order for backwards
        compat. When given a BrokerOrder, looks up the internal Order by local_order_id.
        """
        from .shadow_broker import Quote as ShadowQuote
        if isinstance(broker_order_or_order, BrokerOrder):
            local_id = broker_order_or_order.local_order_id or broker_order_or_order.broker_order_id
            order = self._broker.get_order(local_id)
            if not order:
                return None
        else:
            order = broker_order_or_order
        shadow_q = ShadowQuote(
            bid=quote.bid,
            ask=quote.ask,
            timestamp="",
            market_timestamp=quote.market_timestamp,
            retrieved_at=quote.retrieved_at,
            source=quote.source,
        )
        return self._broker.attempt_fill(order, shadow_q)

    def poll_order_events(
        self, account_id: str, quote: Optional[BrokerQuote] = None
    ) -> list[BrokerOrderEvent]:
        """Simulate order events synchronously for shadow mode (0248, 0256, 0259).

        For each WORKING/PARTIALLY_FILLED order, attempts a fill using the provided quote
        (if fresh and symbol matches) or a freshly fetched quote when no quote is supplied.
        Returns BrokerOrderEvent list; fill events carry broker_fill_id so apply_broker_fill()
        can deduplicate via the idempotency gate (0252).

        Freshness: a stale quote (older than _SHADOW_STALE_MINUTES) never triggers a
        simulated fill — this preserves the test guarantee that stale quotes block fills (0259).
        Expired orders produce EXPIRED events regardless of quote state.
        """
        _SHADOW_STALE_MINUTES = 15  # conservative default; real policy not available here

        events: list[BrokerOrderEvent] = []
        open_orders = self.get_open_orders(account_id)
        for bo in open_orders:
            order = self.get_order(bo.local_order_id or bo.broker_order_id)
            if not order:
                continue

            # Choose effective quote: use passed quote only when symbol matches; else fetch per-order
            effective_quote: Optional[BrokerQuote] = None
            if quote is not None and getattr(quote, "symbol", "") == order.symbol:
                effective_quote = quote
            elif quote is None:
                effective_quote = self.get_quote(order.symbol)

            # Only attempt fill when quote is present AND fresh (0259)
            if effective_quote and _shadow_quote_fresh(effective_quote, _SHADOW_STALE_MINUTES):
                fill = self.attempt_fill(order, effective_quote)
                if fill:
                    event_type = (
                        "FILLED"
                        if float(order.fill_qty or 0) + float(fill.qty) >= float(order.quantity or 0)
                        else "PARTIALLY_FILLED"
                    )
                    events.append(BrokerOrderEvent(
                        event_type=event_type,
                        broker_order_id=order.broker_order_id,
                        local_order_id=order.local_order_id,
                        fill_qty=fill.qty,
                        fill_price=fill.price,
                        filled_at=fill.filled_at,
                        fee=fill.fee,
                        broker_fill_id=fill.fill_id,       # canonical ID for deduplication (0256)
                        client_order_id=order.client_order_id,  # propagate for three-tier resolver (0273)
                    ))
            # Check for expiry after fill attempt (0259): re-read via get_order returns BrokerOrder
            refreshed = self.get_order(bo.local_order_id or bo.broker_order_id)
            if refreshed and refreshed.state == "EXPIRED":
                events.append(BrokerOrderEvent(
                    event_type="EXPIRED",
                    broker_order_id=order.broker_order_id,
                    local_order_id=order.local_order_id,
                ))
        return events

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
