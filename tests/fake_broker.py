"""FakeBrokerAdapter: configurable hostile broker for chaos testing (0249, 0260).

Usage:
    broker = FakeBrokerAdapter(conn, "ACCOUNT_ID", delay_ack=True, duplicate_fills=True)
    adapter = FakeBrokerAdapter(conn, "ACCOUNT_ID", submit_timeout=True)
"""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from trade_engine.broker_adapter import ShadowBrokerAdapter
from trade_engine.broker_types import (
    BrokerAccountState, BrokerFill, BrokerOrder, BrokerOrderEvent,
    BrokerPosition, BrokerQuote,
)
from trade_engine.models import Fill, Order, OrderState, TradeIntent


class FakeBrokerAdapter(ShadowBrokerAdapter):
    """Hostile broker adapter for chaos testing (0249, 0260).

    Every failure mode is opt-in via constructor kwargs. Extends ShadowBrokerAdapter
    so defaults use real shadow simulation; chaos flags layer on top.

    The _broker_orders dict is the independent in-memory broker-side ledger (0260). It is
    intentionally separate from the local SQLite DB so submit_timeout can model the real
    crash scenario: broker accepted the order (wrote to _broker_orders) but the network
    response was lost before reaching the caller (TimeoutError).

    Failure modes:
        delay_ack: submit_order succeeds on Nth call only (simulates slow network)
        duplicate_fills: poll_order_events returns each fill event twice
        out_of_order: poll_order_events reverses event order
        cancel_race: FILLED event emitted simultaneously with cancel
        submit_timeout: submit_order writes broker-side record then raises TimeoutError
        crash_after_submit: submit_order succeeds once, then raises on restart
        position_mismatch: get_positions returns qty different from local DB
        stale_quote: get_quote returns quote with retrieved_at far in the past
    """

    def __init__(
        self,
        conn: sqlite3.Connection,
        account_id: str,
        *,
        delay_ack: int = 0,          # succeed after this many calls (0 = immediate)
        duplicate_fills: bool = False,
        out_of_order: bool = False,
        cancel_race: bool = False,
        submit_timeout: bool = False,
        submit_lost: bool = False,
        crash_after_submit: bool = False,
        position_mismatch_qty: Optional[float] = None,  # override qty returned by get_positions
        stale_quote: bool = False,
    ) -> None:
        super().__init__(conn, account_id)
        self._delay_ack = delay_ack
        self._submit_calls = 0
        self._duplicate_fills = duplicate_fills
        self._out_of_order = out_of_order
        self._cancel_race = cancel_race
        self._submit_timeout = submit_timeout
        self._submit_lost = submit_lost
        self._crash_after_submit = crash_after_submit
        self._crash_submitted = False
        self._position_mismatch_qty = position_mismatch_qty
        self._stale_quote = stale_quote
        # Independent broker-side ledger (0260): keyed by broker_order_id.
        # This dict is the single source of truth for what the broker believes;
        # the local SQLite DB tracks what the engine believes.
        self._broker_orders: dict[str, BrokerOrder] = {}

    def submit_order(self, intent: TradeIntent, client_order_id: Optional[str] = None) -> Order:
        if self._submit_lost:
            # Pure network failure (0265): raises WITHOUT writing to _broker_orders.
            # Broker definitively does not have this order.
            raise TimeoutError("network failure: broker never received order (chaos: submit_lost)")
        if self._submit_timeout:
            # Accepted-but-response-lost (0260): write broker-side record first (broker accepted),
            # then raise before returning — local DB stays at PENDING_SUBMIT, broker has WORKING.
            broker_order_id = str(uuid.uuid4())
            now_str = datetime.now(timezone.utc).isoformat()
            self._broker_orders[broker_order_id] = BrokerOrder(
                broker_order_id=broker_order_id,
                symbol=intent.symbol,
                side=intent.side,
                quantity=float(intent.quantity),
                fill_qty=0.0,
                state="WORKING",
                limit_price=float(intent.limit_price) if intent.limit_price is not None else None,
                client_order_id=client_order_id,
                local_order_id=None,
            )
            raise TimeoutError("broker submission timed out (chaos: submit_timeout)")
        if self._crash_after_submit:
            if self._crash_submitted:
                raise RuntimeError("broker crash after submit (chaos: crash_after_submit)")
            self._crash_submitted = True
        if self._delay_ack > 0:
            self._submit_calls += 1
            if self._submit_calls <= self._delay_ack:
                raise TimeoutError(f"broker ACK delayed (chaos: delay_ack, call {self._submit_calls}/{self._delay_ack})")
        order = super().submit_order(intent, client_order_id=client_order_id)
        # Mirror successful submissions into the in-memory ledger too
        if order:
            self._broker_orders[order.order_id] = BrokerOrder(
                broker_order_id=order.order_id,
                symbol=intent.symbol,
                side=intent.side,
                quantity=float(intent.quantity),
                fill_qty=0.0,
                state="WORKING",
                limit_price=float(intent.limit_price) if intent.limit_price is not None else None,
                client_order_id=client_order_id,
                local_order_id=order.order_id,
            )
        return order

    def get_open_orders(self, account_id: str) -> list[BrokerOrder]:
        """Return union of in-memory ledger and DB-backed orders (0260).

        The in-memory ledger is authoritative for orders created by this adapter
        instance (including submit_timeout orders that never reached the DB).
        """
        db_orders = super().get_open_orders(account_id)
        db_order_ids = {o.broker_order_id for o in db_orders}
        # Add in-memory-only orders not yet in DB (e.g. submit_timeout scenario)
        extra = [
            bo for bid, bo in self._broker_orders.items()
            if bid not in db_order_ids and bo.state in ("WORKING", "PARTIALLY_FILLED")
        ]
        return db_orders + extra

    def get_positions(self, account_id: str) -> list[BrokerPosition]:
        positions = super().get_positions(account_id)
        if self._position_mismatch_qty is not None:
            return [
                BrokerPosition(
                    symbol=p.symbol,
                    qty=self._position_mismatch_qty,
                    avg_cost=p.avg_cost,
                    instrument_type=p.instrument_type,
                    market_price=p.market_price,
                    market_value=p.market_value,
                )
                for p in positions
            ]
        return positions

    def get_quote(self, symbol: str) -> Optional[BrokerQuote]:
        if self._stale_quote:
            # Return a quote that is 999 minutes old — always stale
            stale_ts = datetime.fromtimestamp(
                datetime.now(timezone.utc).timestamp() - 999 * 60,
                tz=timezone.utc,
            ).isoformat()
            return BrokerQuote(
                bid=100.0, ask=101.0, symbol=symbol,
                retrieved_at=stale_ts, source="chaos_stale",
            )
        return super().get_quote(symbol)

    def poll_order_events(
        self, account_id: str, quote: Optional[BrokerQuote] = None
    ) -> list[BrokerOrderEvent]:
        events = super().poll_order_events(account_id, quote=quote)

        if self._duplicate_fills:
            fill_events = [e for e in events if e.event_type in ("FILLED", "PARTIALLY_FILLED")]
            events = events + fill_events  # duplicate fill events

        if self._out_of_order:
            events = list(reversed(events))

        if self._cancel_race and events:
            # Inject a CANCELLED event alongside the first FILLED event
            for e in events:
                if e.event_type == "FILLED":
                    events.append(BrokerOrderEvent(
                        event_type="CANCELLED",
                        broker_order_id=e.broker_order_id,
                        local_order_id=e.local_order_id,
                    ))
                    break

        return events
