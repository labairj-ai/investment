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
from . import market_calendar


class Quote(NamedTuple):
    """Shadow-mode quote with legacy timestamp field. Used by ShadowBroker internals.

    BrokerAdapter.get_quote() returns BrokerQuote (broker_types.py) — the normalized
    type that flows through the adapter boundary. Quote stays here for shadow internals
    and existing test fixtures (0237).
    """
    bid: float
    ask: float
    timestamp: str = ""
    market_timestamp: Optional[str] = None  # when exchange last published this quote
    retrieved_at: Optional[str] = None       # when we fetched it
    source: str = "yfinance"


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


class ShadowBroker:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ── Order submission ──────────────────────────────────────────────────────

    def submit_order(self, intent: TradeIntent) -> Order:
        """Create order row in SUBMITTED→WORKING state (idempotent).

        Uses INSERT OR IGNORE backed by a unique index on intent_id (0206).
        Always re-queries after insert so the canonical DB row is returned.
        Sets expires_at: DAY orders expire at next session close; GTC uses intent.valid_until (0209).
        """
        now = _now_utc().isoformat()
        order_id = str(uuid.uuid4())
        if intent.time_in_force == TimeInForce.DAY:
            # Normalize to UTC so expiry comparisons are timezone-safe (0219)
            expires_at = market_calendar.next_market_close().astimezone(timezone.utc).isoformat()
        else:
            expires_at = intent.valid_until
        self._conn.execute(
            """INSERT OR IGNORE INTO orders
               (order_id, intent_id, account_id, symbol, side, quantity,
                contracts, order_type, limit_price, state, time_in_force,
                submitted_at, updated_at, fill_qty, fill_cash, expires_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                order_id, intent.intent_id, intent.account_id, intent.symbol,
                intent.side.value, intent.quantity, intent.contracts,
                intent.order_type.value, intent.limit_price,
                OrderState.SUBMITTED.value, intent.time_in_force.value,
                now, now, 0.0, 0.0, expires_at,
            ),
        )
        self._conn.commit()

        # Always re-query: returns either the row we just inserted or a pre-existing one
        row = self._conn.execute(
            "SELECT * FROM orders WHERE intent_id=?", (intent.intent_id,)
        ).fetchone()
        order = Order.from_db_row(row)

        # Advance SUBMITTED → WORKING if not already past that state
        if order.state == OrderState.SUBMITTED:
            self._transition_order(order, OrderState.WORKING)

        return order

    # ── Fill simulation ───────────────────────────────────────────────────────

    def attempt_fill(self, order: Order, quote: Quote) -> Optional[Fill]:
        """Simulate a fill. Returns Fill on success, None if price/session conditions not met.

        Expiry check: expires_at in the past → EXPIRED (for all TIF). (0209)
        Session gate: no fills outside regular trading session for any TIF. (0209)
        Quote sanity: bid > 0, ask > 0, bid <= ask. (0213)
        """
        if order.state not in (OrderState.WORKING, OrderState.PARTIALLY_FILLED):
            return None

        # Quote sanity checks: reject clearly bad quotes (0213)
        if quote.bid <= 0 or quote.ask <= 0 or quote.bid > quote.ask:
            return None

        # Expiry check (0219): parse to aware datetimes — never compare ISO strings across TZs
        if order.expires_at:
            expiry = datetime.fromisoformat(
                order.expires_at.replace("Z", "+00:00")
            ).astimezone(timezone.utc)
            if _now_utc() >= expiry:
                self._transition_order(order, OrderState.EXPIRED)
                return None

        # Session gate (0209): all TIF respect regular session; remain WORKING outside hours
        if not market_calendar.is_market_open():
            return None

        # Market orders are rejected (policy should have caught this, but guard again)
        if order.order_type == OrderType.MARKET:
            self._transition_order(order, OrderState.REJECTED)
            return None

        # Determine fill price from limit conditions
        fill_price = self._fill_price(order, quote)
        if fill_price is None:
            return None

        # Fill only the remaining (unfilled) quantity (0224)
        qty = (order.quantity or 0.0) - (order.fill_qty or 0.0)
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
            if quote.ask <= lim:
                return quote.ask
        elif side in (Side.SELL, Side.SELL_TO_OPEN):
            if quote.bid >= lim:
                return quote.bid
        return None

    def _apply_fill(self, order: Order, fill: Fill) -> None:
        """Write fill and update positions + cash atomically, capturing realized P&L (0202)."""
        # Idempotency: skip if fill_id already exists
        existing = self._conn.execute(
            "SELECT fill_id FROM fills WHERE fill_id=?", (fill.fill_id,)
        ).fetchone()
        if existing:
            return

        is_buy = fill.side in (Side.BUY, Side.BUY_TO_CLOSE)
        is_sell = not is_buy

        # ── Capture realized P&L before position mutation (0202) ─────────────
        cost_basis = 0.0
        realized_pnl = 0.0
        realized_pnl_pct = 0.0
        if is_sell:
            pos_row = self._conn.execute(
                "SELECT qty, avg_cost FROM position_snapshots WHERE account_id=? AND symbol=?",
                (fill.account_id, fill.symbol),
            ).fetchone()
            if pos_row:
                avg_cost = float(pos_row["avg_cost"] or 0)
                cost_basis = fill.qty * avg_cost
                proceeds = fill.qty * fill.price - fill.fee
                realized_pnl = proceeds - cost_basis
                realized_pnl_pct = (realized_pnl / cost_basis * 100) if cost_basis else 0.0

        cash_delta = fill.cash_impact()

        # Write fill with realized P&L
        self._conn.execute(
            """INSERT INTO fills
               (fill_id, order_id, account_id, symbol, side,
                qty, price, fee, fill_source, filled_at,
                cost_basis, realized_pnl, realized_pnl_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                fill.fill_id, fill.order_id, fill.account_id, fill.symbol,
                fill.side.value, fill.qty, fill.price, fill.fee,
                fill.fill_source, fill.filled_at,
                cost_basis, realized_pnl, realized_pnl_pct,
            ),
        )

        # Update order fill_qty / fill_cash / state (0224)
        new_fill_qty = order.fill_qty + fill.qty
        new_fill_cash = order.fill_cash + fill.qty * fill.price
        order.fill_qty = new_fill_qty
        order.fill_cash = new_fill_cash
        total_qty = order.quantity or 0.0
        new_state = OrderState.FILLED if new_fill_qty >= total_qty else OrderState.PARTIALLY_FILLED
        self._transition_order(order, new_state, commit=False)
        self._conn.execute(
            """UPDATE orders SET fill_qty=?, fill_cash=?, state=?, updated_at=?
               WHERE order_id=?""",
            (new_fill_qty, new_fill_cash, order.state.value,
             order.updated_at, order.order_id),
        )

        # Update position_snapshots with conflict handling for unique constraint (0206)
        existing_pos = self._conn.execute(
            "SELECT qty, avg_cost, market_price, price_as_of FROM position_snapshots WHERE account_id=? AND symbol=?",
            (fill.account_id, fill.symbol),
        ).fetchone()

        if existing_pos:
            old_qty = float(existing_pos["qty"])
            old_avg = float(existing_pos["avg_cost"])
            old_market_price = float(existing_pos["market_price"]) if existing_pos["market_price"] is not None else None
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
                # 0231: keep market_value coherent — use existing mark if available, else fill price
                mark = old_market_price if old_market_price is not None else fill.price
                new_market_value = new_qty * mark
                price_as_of = fill.filled_at if old_market_price is None else existing_pos["price_as_of"]
                self._conn.execute(
                    """UPDATE position_snapshots
                       SET qty=?, avg_cost=?, as_of=?, market_price=?, market_value=?, price_as_of=?
                       WHERE account_id=? AND symbol=?""",
                    (new_qty, new_avg, fill.filled_at,
                     mark, new_market_value, price_as_of,
                     fill.account_id, fill.symbol),
                )
        elif is_buy:
            # 0231, 0239: atomic UPSERT — single writer invariant; no race between INSERT and UPDATE.
            # ON CONFLICT accumulates qty and recomputes avg_cost atomically.
            self._conn.execute(
                """INSERT INTO position_snapshots
                   (account_id, symbol, qty, avg_cost, instrument_type, as_of,
                    market_price, market_value, price_as_of)
                   VALUES (?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(account_id, symbol) DO UPDATE SET
                       avg_cost = (qty * avg_cost + excluded.qty * excluded.avg_cost)
                                  / (qty + excluded.qty),
                       qty      = qty + excluded.qty,
                       as_of    = excluded.as_of,
                       market_price  = excluded.market_price,
                       market_value  = (qty + excluded.qty) * excluded.market_price,
                       price_as_of   = excluded.price_as_of""",
                (fill.account_id, fill.symbol, fill.qty, fill.price, "EQUITY", fill.filled_at,
                 fill.price, fill.qty * fill.price, fill.filled_at),
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

    def cancel_order(self, order_id: str, reason: str = "USER_REQUESTED") -> Order:
        """Cancel an order, recording the reason (0236).

        Shadow mode: CANCEL_REQUESTED → CANCELLED is synchronous (no broker round-trip).
        For paper/live adapters these two transitions will be separated by an async ACK.
        cancel_reason, cancel_requested_at, cancel_confirmed_at are written if the columns
        exist (added by agent_db._new_cols; gracefully ignored if schema is older).
        """
        row = self._conn.execute(
            "SELECT * FROM orders WHERE order_id=?", (order_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Order {order_id!r} not found")
        order = Order.from_db_row(row)
        now_iso = _now_utc().isoformat()
        self._transition_order(order, OrderState.CANCEL_REQUESTED, commit=False)
        self._transition_order(order, OrderState.CANCELLED, commit=False)
        try:
            self._conn.execute(
                "UPDATE orders SET cancel_reason=?, cancel_requested_at=?, cancel_confirmed_at=? WHERE order_id=?",
                (reason, now_iso, now_iso, order_id),
            )
        except Exception:
            pass  # columns may not exist on older schemas
        self._conn.commit()
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
            is_option_leg = f["side"] in ("SELL_TO_OPEN", "BUY_TO_CLOSE")
            multiplier = 100 if is_option_leg else 1
            if f["side"] in ("SELL", "SELL_TO_OPEN"):
                computed_cash += qty * price * multiplier - fee
            else:
                computed_cash -= qty * price * multiplier + fee

        diff = abs(computed_cash - current)
        return {
            "ok": diff < 0.01,
            "expected": round(computed_cash, 6),
            "actual": round(current, 6),
            "diff": round(diff, 6),
        }
