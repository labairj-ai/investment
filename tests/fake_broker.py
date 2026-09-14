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
    BrokerAccountState, BrokerCancelAck, BrokerFill, BrokerOrder, BrokerOrderAck, BrokerOrderEvent,
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
        submit_lost: submit_order raises WITHOUT writing to _broker_orders (pure network loss)
        crash_after_submit: submit_order succeeds once, then raises on restart
        position_mismatch: get_positions returns qty different from local DB
        stale_quote: get_quote returns quote with retrieved_at far in the past
        distinct_broker_id: submit_order returns a broker_order_id different from local order_id (0268)
        ack_state: normalized_state returned in BrokerOrderAck (default "WORKING") (0271)
        broker_account_id: ID returned by get_account_id() (default matches account_id) (0272)
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
        distinct_broker_id: bool = False,    # broker_order_id ≠ local order_id (0268)
        ack_state: str = "WORKING",          # normalized_state in returned BrokerOrderAck (0271)
        broker_account_id: Optional[str] = None,  # overrides get_account_id() response (0272)
        fill_raises: bool = False,           # get_fills_for_order raises RuntimeError (0278)
        no_fill_id_events: bool = False,     # poll events omit broker_fill_id (0283)
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
        self._distinct_broker_id = distinct_broker_id
        self._ack_state = ack_state
        self._broker_account_id = broker_account_id
        self._fill_raises = fill_raises
        self._no_fill_id_events = no_fill_id_events
        # Independent broker-side ledger (0260): keyed by broker_order_id.
        # This dict is the single source of truth for what the broker believes;
        # the local SQLite DB tracks what the engine believes.
        self._broker_orders: dict[str, BrokerOrder] = {}
        # Mapping broker_order_id → local order_id for distinct_broker_id mode (0268)
        self._broker_to_local: dict[str, str] = {}
        # Broker fill ledger keyed by broker_order_id (0273): authoritative fill data
        # pre-staged when ack_state=="FILLED" or manually set by tests (0274/0277).
        self._broker_fills: dict[str, list[BrokerFill]] = {}

    def submit_order(self, intent: TradeIntent, client_order_id: Optional[str] = None) -> BrokerOrderAck:
        if self._submit_lost:
            # Pure network failure (0265): raises WITHOUT writing to _broker_orders.
            # Broker definitively does not have this order.
            raise TimeoutError("network failure: broker never received order (chaos: submit_lost)")
        if self._submit_timeout:
            # Accepted-but-response-lost (0260): write broker-side record first (broker accepted),
            # then raise before returning — local DB stays at PENDING_SUBMIT, broker has WORKING.
            broker_order_id = str(uuid.uuid4())
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
        ack = super().submit_order(intent, client_order_id=client_order_id)
        local_oid = ack.broker_order_id  # in shadow mode, broker_order_id == local order_id

        if self._distinct_broker_id:
            # Generate a separate broker-native ID, distinct from the local order_id (0268).
            # Update DB so broker_order_id column is set to the new UUID.
            new_broker_oid = str(uuid.uuid4())
            self._conn.execute(
                "UPDATE orders SET broker_order_id=? WHERE order_id=?",
                (new_broker_oid, local_oid),
            )
            self._conn.commit()
            self._broker_to_local[new_broker_oid] = local_oid
            ack = BrokerOrderAck(
                broker_order_id=new_broker_oid,
                client_order_id=client_order_id,
                normalized_state=self._ack_state,
                accepted_at=ack.accepted_at,
                raw_status=ack.raw_status,
            )
            _bo_state = {"FILLED": "FILLED", "PARTIALLY_FILLED": "PARTIALLY_FILLED"}.get(self._ack_state, "WORKING")
            _pf_qty = float(intent.quantity) if self._ack_state == "FILLED" else (float(intent.quantity) / 2 if self._ack_state == "PARTIALLY_FILLED" else 0.0)
            self._broker_orders[new_broker_oid] = BrokerOrder(
                broker_order_id=new_broker_oid,
                symbol=intent.symbol,
                side=intent.side,
                quantity=float(intent.quantity),
                fill_qty=_pf_qty,
                state=_bo_state,
                limit_price=float(intent.limit_price) if intent.limit_price is not None else None,
                client_order_id=client_order_id,
                local_order_id=local_oid,
            )
            if self._ack_state in ("FILLED", "PARTIALLY_FILLED"):
                self._broker_fills[new_broker_oid] = [self._make_broker_fill(
                    new_broker_oid, local_oid, intent, client_order_id, ack.accepted_at, qty=_pf_qty,
                )]
        else:
            ack = BrokerOrderAck(
                broker_order_id=ack.broker_order_id,
                client_order_id=client_order_id,
                normalized_state=self._ack_state,
                accepted_at=ack.accepted_at,
                raw_status=ack.raw_status,
            )
            _bo_state = {"FILLED": "FILLED", "PARTIALLY_FILLED": "PARTIALLY_FILLED"}.get(self._ack_state, "WORKING")
            _pf_qty = float(intent.quantity) if self._ack_state == "FILLED" else (float(intent.quantity) / 2 if self._ack_state == "PARTIALLY_FILLED" else 0.0)
            self._broker_orders[ack.broker_order_id] = BrokerOrder(
                broker_order_id=ack.broker_order_id,
                symbol=intent.symbol,
                side=intent.side,
                quantity=float(intent.quantity),
                fill_qty=_pf_qty,
                state=_bo_state,
                limit_price=float(intent.limit_price) if intent.limit_price is not None else None,
                client_order_id=client_order_id,
                local_order_id=ack.broker_order_id,
            )
            if self._ack_state in ("FILLED", "PARTIALLY_FILLED"):
                self._broker_fills[ack.broker_order_id] = [self._make_broker_fill(
                    ack.broker_order_id, local_oid, intent, client_order_id, ack.accepted_at, qty=_pf_qty,
                )]
        return ack

    def _make_broker_fill(
        self, broker_order_id: str, local_order_id: str, intent, client_order_id, accepted_at, *, qty=None,
    ) -> BrokerFill:
        """Pre-stage a broker-authoritative fill for FILLED/PARTIALLY_FILLED ACK mode (0273, 0280)."""
        side_str = intent.side.value if hasattr(intent.side, "value") else str(intent.side)
        fill_price = float(intent.limit_price) if intent.limit_price is not None else 100.0
        fill_qty = float(qty) if qty is not None else float(intent.quantity)
        return BrokerFill(
            broker_fill_id=f"fake-fill-{broker_order_id}",
            broker_order_id=broker_order_id,
            symbol=intent.symbol,
            side=side_str,
            qty=fill_qty,
            price=fill_price,
            filled_at=accepted_at or datetime.now(timezone.utc).isoformat(),
            fee=0.01,
            local_order_id=local_order_id,
            account_id=intent.account_id,
            client_order_id=client_order_id,
        )

    def get_order(self, order_id: str):
        # Translate broker_order_id → local order_id for distinct_broker_id mode (0268)
        local_id = self._broker_to_local.get(order_id, order_id)
        return super().get_order(local_id)

    def cancel_order(self, order_id: str, reason: str = "USER_REQUESTED") -> BrokerCancelAck:
        # Translate broker_order_id → local order_id for distinct_broker_id mode (0268)
        local_id = self._broker_to_local.get(order_id, order_id)
        return super().cancel_order(local_id, reason=reason)

    def get_fills_for_order(self, broker_order_id: str) -> list[BrokerFill]:
        """Return pre-staged broker fills from the in-memory ledger (0273).

        Raises RuntimeError when fill_raises=True — simulates a broker fill endpoint
        failure to test BrokerSettlementIndeterminate handling (0278).
        """
        if self._fill_raises:
            raise RuntimeError("chaos: get_fills_for_order raised (fill_raises=True)")
        return list(self._broker_fills.get(broker_order_id, []))

    def find_order_by_client_order_id(self, client_order_id: str):
        """Search in-memory broker ledger only (0270); DB is local, not broker, for fake mode."""
        for bo in self._broker_orders.values():
            if bo.client_order_id == client_order_id:
                return bo
        return None

    def get_account_id(self) -> str:
        """Return configurable broker account ID for account-binding chaos tests (0272)."""
        return self._broker_account_id if self._broker_account_id is not None else self.account_id

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

        if self._no_fill_id_events:
            events = [
                BrokerOrderEvent(
                    event_type=e.event_type,
                    broker_order_id=e.broker_order_id,
                    local_order_id=e.local_order_id,
                    fill_qty=e.fill_qty,
                    fill_price=e.fill_price,
                    filled_at=e.filled_at,
                    fee=e.fee,
                    broker_fill_id=None,
                    client_order_id=e.client_order_id,
                ) if e.event_type in ("FILLED", "PARTIALLY_FILLED") else e
                for e in events
            ]

        return events
