"""ShadowBroker: simulated order lifecycle and fill engine (0194)."""
from __future__ import annotations

import sqlite3
import uuid
from datetime import datetime, timezone
from typing import NamedTuple, Optional

from .models import (
    Fill,
    InvalidStateTransition,
    Order,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
    TradeIntent,
)


class Quote(NamedTuple):
    bid: float
    ask: float
    timestamp: str


_MARKET_CLOSE_HOUR_ET = 16  # 4:00 PM ET


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _is_after_market_close() -> bool:
    """True when current ET time is at or past 16:00 (DAY order expiry)."""
    try:
        import zoneinfo
        et = datetime.now(zoneinfo.ZoneInfo("America/New_York"))
    except Exception:
        # fallback: approximate via UTC-4/UTC-5
        et = _now_utc()
    return et.hour >= _MARKET_CLOSE_HOUR_ET


class ShadowBroker:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Order submission ──────────────────────────────────────────────────────

    def submit_order(self, intent: TradeIntent) -> Order:
        """Create order row in SUBMITTED state (idempotency checkpoint).

        Returns the existing order if one already exists for this intent_id
        (crash-restart safety — no double-submission).
        """
        existing = self._conn.execute(
            "SELECT * FROM orders WHERE intent_id=?", (intent.intent_id,)
        ).fetchone()
        if existing:
            return Order.from_db_row(existing)

        now = _now_utc().isoformat()
        order = Order(
            order_id=str(uuid.uuid4()),
            intent_id=intent.intent_id,
            account_id=intent.account_id,
            symbol=intent.symbol,
            side=intent.side,
            quantity=intent.quantity,
            contracts=intent.contracts,
            order_type=intent.order_type,
            limit_price=intent.limit_price,
            state=OrderState.SUBMITTED,
            time_in_force=intent.time_in_force,
            submitted_at=now,
            updated_at=now,
        )
        d = order.to_db_dict()
        self._conn.execute(
            """INSERT INTO orders
               (order_id, intent_id, account_id, symbol, side, quantity,
                contracts, order_type, limit_price, state, time_in_force,
                submitted_at, updated_at, fill_qty, fill_cash)
               VALUES (:order_id, :intent_id, :account_id, :symbol, :side, :quantity,
                :contracts, :order_type, :limit_price, :state, :time_in_force,
                :submitted_at, :updated_at, :fill_qty, :fill_cash)""",
            d,
        )
        self._conn.commit()

        # SUBMITTED → WORKING immediately (shadow broker has no async submit)
        order.transition(OrderState.WORKING)
        self._conn.execute(
            "UPDATE orders SET state=?, updated_at=? WHERE order_id=?",
            (order.state.value, order.updated_at, order.order_id),
        )
        self._conn.commit()
        return order

    # ── Fill simulation ───────────────────────────────────────────────────────

    def attempt_fill(self, order: Order, quote: Quote) -> Optional[Fill]:
        """Simulate a fill. Returns Fill on success, None if price conditions not met.

        For DAY orders, auto-expires if market is closed.
        """
        if order.state not in (OrderState.WORKING, OrderState.PARTIALLY_FILLED):
            return None

        # Expire DAY orders after market close
        if order.time_in_force == TimeInForce.DAY and _is_after_market_close():
            self._transition_order(order, OrderState.EXPIRED)
            return None

        # Market orders are rejected (policy should have caught this, but guard again)
        if order.order_type == OrderType.MARKET:
            self._transition_order(order, OrderState.REJECTED)
            return None

        # Determine fill price from limit conditions
        fill_price = self._fill_price(order, quote)
        if fill_price is None:
            return None

        qty = order.quantity or 0.0
        if qty <= 0:
            return None

        fee = 0.0  # shadow mode: no commissions
        fill = Fill(
            fill_id=str(uuid.uuid4()),
            order_id=order.order_id,
            account_id=order.account_id,
            symbol=order.symbol,
            side=order.side,
            qty=qty,
            price=fill_price,
            fee=fee,
            fill_source="shadow",
            filled_at=_now_utc().isoformat(),
        )

        self._apply_fill(order, fill)
        return fill

    def _fill_price(self, order: Order, quote: Quote) -> Optional[float]:
        """Return fill price if limit conditions are met, else None."""
        side = order.side
        lim = order.limit_price
        if side in (Side.BUY, Side.BUY_TO_CLOSE):
            # Fills when ask <= limit; at ask (more realistic than limit)
            if quote.ask <= lim:
                return quote.ask
        elif side in (Side.SELL, Side.SELL_TO_OPEN):
            # Fills when bid >= limit; at bid
            if quote.bid >= lim:
                return quote.bid
        return None

    def _apply_fill(self, order: Order, fill: Fill) -> None:
        """Write fill and update positions + cash atomically."""
        # Idempotency: skip if fill_id already exists
        existing = self._conn.execute(
            "SELECT fill_id FROM fills WHERE fill_id=?", (fill.fill_id,)
        ).fetchone()
        if existing:
            return

        cash_delta = fill.cash_impact()
        is_buy = fill.side in (Side.BUY, Side.BUY_TO_CLOSE)

        # Write fill
        self._conn.execute(
            """INSERT INTO fills (fill_id, order_id, account_id, symbol, side,
               qty, price, fee, fill_source, filled_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (fill.fill_id, fill.order_id, fill.account_id, fill.symbol,
             fill.side.value, fill.qty, fill.price, fill.fee,
             fill.fill_source, fill.filled_at),
        )

        # Update order fill_qty / fill_cash / state
        new_fill_qty = order.fill_qty + fill.qty
        new_fill_cash = order.fill_cash + fill.qty * fill.price
        order.fill_qty = new_fill_qty
        order.fill_cash = new_fill_cash
        self._transition_order(order, OrderState.FILLED, commit=False)
        self._conn.execute(
            """UPDATE orders SET fill_qty=?, fill_cash=?, state=?, updated_at=?
               WHERE order_id=?""",
            (new_fill_qty, new_fill_cash, order.state.value,
             order.updated_at, order.order_id),
        )

        # Update position_snapshots
        existing_pos = self._conn.execute(
            "SELECT qty, avg_cost FROM position_snapshots WHERE account_id=? AND symbol=?",
            (fill.account_id, fill.symbol),
        ).fetchone()

        if existing_pos:
            old_qty = float(existing_pos["qty"])
            old_avg = float(existing_pos["avg_cost"])
            if is_buy:
                new_qty = old_qty + fill.qty
                new_avg = (old_qty * old_avg + fill.qty * fill.price) / new_qty if new_qty > 0 else 0.0
            else:
                new_qty = old_qty - fill.qty
                new_avg = old_avg  # avg_cost unchanged on sell
            if new_qty <= 0:
                self._conn.execute(
                    "DELETE FROM position_snapshots WHERE account_id=? AND symbol=?",
                    (fill.account_id, fill.symbol),
                )
            else:
                self._conn.execute(
                    """UPDATE position_snapshots SET qty=?, avg_cost=?, as_of=?
                       WHERE account_id=? AND symbol=?""",
                    (new_qty, new_avg, fill.filled_at, fill.account_id, fill.symbol),
                )
        elif is_buy:
            self._conn.execute(
                """INSERT INTO position_snapshots
                   (account_id, symbol, qty, avg_cost, instrument_type, as_of)
                   VALUES (?,?,?,?,?,?)""",
                (fill.account_id, fill.symbol, fill.qty, fill.price,
                 "EQUITY", fill.filled_at),
            )

        # Update account cash
        self._conn.execute(
            "UPDATE trading_accounts SET current_cash=current_cash+? WHERE account_id=?",
            (cash_delta, fill.account_id),
        )

        self._conn.commit()

    def _transition_order(
        self, order: Order, new_state: OrderState, commit: bool = True
    ) -> None:
        order.transition(new_state)
        self._conn.execute(
            "UPDATE orders SET state=?, updated_at=? WHERE order_id=?",
            (order.state.value, order.updated_at, order.order_id),
        )
        if commit:
            self._conn.commit()

    # ── Queries ───────────────────────────────────────────────────────────────

    def cancel_order(self, order_id: str) -> Order:
        row = self._conn.execute(
            "SELECT * FROM orders WHERE order_id=?", (order_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Order {order_id!r} not found")
        order = Order.from_db_row(row)
        self._transition_order(order, OrderState.CANCELLED)
        return order

    def get_order(self, order_id: str) -> Optional[Order]:
        row = self._conn.execute(
            "SELECT * FROM orders WHERE order_id=?", (order_id,)
        ).fetchone()
        return Order.from_db_row(row) if row else None

    def get_positions(self, account_id: str) -> dict[str, float]:
        rows = self._conn.execute(
            "SELECT symbol, qty FROM position_snapshots WHERE account_id=?",
            (account_id,),
        ).fetchall()
        return {r["symbol"]: float(r["qty"]) for r in rows}

    def get_cash(self, account_id: str) -> float:
        row = self._conn.execute(
            "SELECT current_cash FROM trading_accounts WHERE account_id=?",
            (account_id,),
        ).fetchone()
        return float(row["current_cash"]) if row else 0.0

    def verify_conservation(self, account_id: str) -> dict:
        """Verify cash conservation: starting_capital + sell_cash - buy_cash - fees = current_cash."""
        row = self._conn.execute(
            "SELECT starting_capital, current_cash FROM trading_accounts WHERE account_id=?",
            (account_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "reason": "account not found"}

        starting = float(row["starting_capital"])
        current = float(row["current_cash"])

        fills = self._conn.execute(
            "SELECT side, qty, price, fee FROM fills WHERE account_id=?",
            (account_id,),
        ).fetchall()

        computed_cash = starting
        for f in fills:
            qty = float(f["qty"] or 0)
            price = float(f["price"] or 0)
            fee = float(f["fee"] or 0)
            if f["side"] in ("SELL", "SELL_TO_OPEN"):
                computed_cash += qty * price - fee
            else:
                computed_cash -= qty * price + fee

        diff = abs(computed_cash - current)
        return {
            "ok": diff < 0.01,
            "expected": round(computed_cash, 6),
            "actual": round(current, 6),
            "diff": round(diff, 6),
        }
