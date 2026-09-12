"""ExecutionEngine: orchestrates Intent → Risk → Shadow → Fill → executed_actions (0196).

Cycle architecture (0199):
  run_execution_cycle()
    process_new_intents()  — PENDING intents only; risk evaluate + submit order
    process_open_orders()  — WORKING/PARTIALLY_FILLED orders; refresh MtM, attempt fills
"""
from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from .models import (
    ExecutionResult,
    Fill,
    IntentStatus,
    Order,
    OrderState,
    TradeIntent,
    TradingAccount,
)
from .policy import TradingPolicy, load_policy
from .risk_engine import evaluate as risk_evaluate
from .shadow_broker import Quote, ShadowBroker

_log = logging.getLogger(__name__)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_quote(symbol: str) -> Optional[Quote]:
    """Fetch live bid/ask from yfinance. Returns None on any failure (0200).

    Populates market_timestamp from yfinance when available; bid <= ask sanity
    check is enforced in attempt_fill, not here (0213).
    """
    try:
        import yfinance as yf
        retrieved_at = _now_utc().isoformat()
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        bid = float(getattr(info, "bid", None) or 0)
        ask = float(getattr(info, "ask", None) or 0)
        last = float(getattr(info, "last_price", None) or 0)
        if bid <= 0:
            bid = last
        if ask <= 0:
            ask = last
        if bid > 0 and ask > 0:
            # Attempt to get exchange-side timestamp (not always available)
            market_ts = None
            try:
                rmt = getattr(info, "regular_market_time", None)
                if rmt:
                    from datetime import datetime as _dt
                    market_ts = _dt.fromtimestamp(float(rmt), tz=timezone.utc).isoformat()
            except Exception:
                pass
            return Quote(
                bid=bid, ask=ask,
                timestamp=retrieved_at,
                market_timestamp=market_ts,
                retrieved_at=retrieved_at,
                source="yfinance",
            )
    except Exception:
        pass
    return None


def _load_account(account_id: str, conn: sqlite3.Connection) -> Optional[TradingAccount]:
    row = conn.execute(
        "SELECT * FROM trading_accounts WHERE account_id=?", (account_id,)
    ).fetchone()
    return TradingAccount.from_db_row(row) if row else None


def _update_intent_status(intent_id: str, status: IntentStatus, conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE trade_intents SET status=? WHERE intent_id=?",
        (status.value, intent_id),
    )
    conn.commit()


def _sync_intent_from_order(order: Order, intent_id: str, conn: sqlite3.Connection) -> None:
    """Keep intent status in sync with order terminal states."""
    _TERMINAL_MAP = {
        OrderState.FILLED: IntentStatus.FILLED,
        OrderState.CANCELLED: IntentStatus.EXPIRED,
        OrderState.EXPIRED: IntentStatus.EXPIRED,
        OrderState.REJECTED: IntentStatus.REJECTED,
        OrderState.ERROR: IntentStatus.REJECTED,
    }
    if order.state in _TERMINAL_MAP:
        _update_intent_status(intent_id, _TERMINAL_MAP[order.state], conn)


def _write_executed_action(fill: Fill, intent: TradeIntent, conn: sqlite3.Connection) -> None:
    """Write shadow fill to executed_actions for outcome evaluator integration."""
    conn.execute(
        """INSERT OR IGNORE INTO executed_actions
           (recommendation_id, ticker, action, quantity, execution_price,
            execution_date, fees, notes, source, created_at, fill_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            intent.recommendation_id,
            fill.symbol,
            fill.side.value,
            fill.qty,
            fill.price,
            fill.filled_at[:10],
            fill.fee,
            f"shadow fill_source={fill.fill_source}",
            "shadow",
            time.time(),
            fill.fill_id,
        ),
    )
    conn.commit()


def _refresh_market_prices(account_id: str, conn: sqlite3.Connection) -> None:
    """Update market_price/market_value on position_snapshots for all holdings (0201)."""
    rows = conn.execute(
        "SELECT symbol FROM position_snapshots WHERE account_id=?",
        (account_id,),
    ).fetchall()
    for row in rows:
        symbol = row["symbol"]
        quote = _get_quote(symbol)
        if not quote:
            continue
        mid = (quote.bid + quote.ask) / 2.0
        market_value_per_unit = mid
        conn.execute(
            """UPDATE position_snapshots
               SET market_price=?, market_value=qty*?, price_as_of=?
               WHERE account_id=? AND symbol=?""",
            (mid, market_value_per_unit, quote.timestamp, account_id, symbol),
        )
    conn.commit()


def _write_account_snapshot(
    account_id: str, conn: sqlite3.Connection, reason: str = "cycle"
) -> None:
    """Write a point-in-time account snapshot to account_snapshots (0214)."""
    from .risk_engine import _open_buy_notional as _obn
    acct = conn.execute(
        "SELECT current_cash FROM trading_accounts WHERE account_id=?",
        (account_id,),
    ).fetchone()
    if not acct:
        return
    cash = float(acct["current_cash"] or 0)
    pos_rows = conn.execute(
        "SELECT qty, avg_cost, market_value FROM position_snapshots WHERE account_id=?",
        (account_id,),
    ).fetchall()
    gross_exposure = 0.0
    unrealized_pnl = 0.0
    for r in pos_rows:
        mv = r["market_value"] if "market_value" in r.keys() and r["market_value"] is not None else None
        cost = float(r["qty"] or 0) * float(r["avg_cost"] or 0)
        val = float(mv) if mv is not None else cost
        gross_exposure += val
        unrealized_pnl += val - cost
    nav = cash + gross_exposure
    open_order_notional = _obn(account_id, conn)
    reserved_cash = open_order_notional
    buying_power = max(0.0, cash - reserved_cash)
    realized_pnl_today_row = conn.execute(
        """SELECT COALESCE(SUM(realized_pnl), 0) AS t
           FROM fills WHERE account_id=? AND DATE(filled_at)=DATE('now')""",
        (account_id,),
    ).fetchone()
    realized_pnl_today = float(realized_pnl_today_row["t"] or 0)
    snapshot_at = _now_utc().isoformat()
    try:
        conn.execute(
            """INSERT INTO account_snapshots
               (account_id, cash, nav, buying_power, snapshot_at,
                gross_exposure, reserved_cash, open_order_notional,
                realized_pnl_today, unrealized_pnl, snapshot_reason)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (account_id, cash, nav, buying_power, snapshot_at,
             gross_exposure, reserved_cash, open_order_notional,
             realized_pnl_today, unrealized_pnl, reason),
        )
    except Exception:
        # Fallback: base 4-column insert for schemas without the new columns
        conn.execute(
            "INSERT INTO account_snapshots (account_id, cash, nav, buying_power, snapshot_at) VALUES (?,?,?,?,?)",
            (account_id, cash, nav, buying_power, snapshot_at),
        )
    conn.commit()


def _update_nav_high_water(account_id: str, conn: sqlite3.Connection) -> None:
    """Update nav_high_water when current NAV exceeds prior peak (0201)."""
    acct = conn.execute(
        "SELECT current_cash, nav_high_water FROM trading_accounts WHERE account_id=?",
        (account_id,),
    ).fetchone()
    if not acct:
        return
    cash = float(acct["current_cash"] or 0)
    pos_rows = conn.execute(
        "SELECT qty, avg_cost, market_value FROM position_snapshots WHERE account_id=?",
        (account_id,),
    ).fetchall()
    pos_value = 0.0
    for r in pos_rows:
        mv = r["market_value"] if "market_value" in r.keys() else None
        pos_value += float(mv) if mv is not None else float(r["qty"] or 0) * float(r["avg_cost"] or 0)
    current_nav = cash + pos_value
    prior_hw = float(acct["nav_high_water"] or 0) if acct["nav_high_water"] else 0.0
    if current_nav > prior_hw:
        conn.execute(
            "UPDATE trading_accounts SET nav_high_water=? WHERE account_id=?",
            (current_nav, account_id),
        )
        conn.commit()


def process_intent(intent_id: str, conn: sqlite3.Connection) -> ExecutionResult:
    """Run the full execution pipeline for a single PENDING intent.

    Fail-closed on missing quote (0200): if _get_quote() returns None, the order
    stays WORKING. process_open_orders() will retry on the next cycle.
    """
    t0 = time.monotonic()

    row = conn.execute(
        "SELECT * FROM trade_intents WHERE intent_id=?", (intent_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Intent {intent_id!r} not found")

    intent = TradeIntent.from_db_row(row)
    account = _load_account(intent.account_id, conn)
    if not account:
        raise ValueError(f"Account {intent.account_id!r} not found")

    try:
        policy = load_policy(intent.account_id)
    except Exception as e:
        raise ValueError(f"Cannot load policy for {intent.account_id!r}: {e}") from e

    # ── Risk evaluation ───────────────────────────────────────────────────────
    risk_decision = risk_evaluate(intent, policy, account, conn)

    if risk_decision.decision == "REJECTED":
        _update_intent_status(intent_id, IntentStatus.REJECTED, conn)
        return ExecutionResult(
            intent_id=intent_id,
            decision="REJECTED",
            order_id=None,
            fill=None,
            risk_decision=risk_decision,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    _update_intent_status(intent_id, IntentStatus.APPROVED, conn)

    # ── Order submission (idempotent via INSERT OR IGNORE) ────────────────────
    broker = ShadowBroker(conn)
    order = broker.submit_order(intent)

    # ── First fill attempt ─────────────────────────────────────────────────────
    existing_fill_row = conn.execute(
        "SELECT * FROM fills WHERE order_id=?", (order.order_id,)
    ).fetchone()

    fill: Optional[Fill] = None
    if existing_fill_row:
        fill = Fill.from_db_row(existing_fill_row)
    elif order.state in (OrderState.WORKING, OrderState.PARTIALLY_FILLED):
        quote = _get_quote(intent.symbol)
        if quote:
            fill = broker.attempt_fill(order, quote)
        else:
            # Fail closed: no quote → mark order, leave WORKING for next cycle
            conn.execute(
                "UPDATE orders SET market_data_status='unavailable' WHERE order_id=?",
                (order.order_id,),
            )
            conn.commit()

    if fill:
        updated_order = broker.get_order(order.order_id)
        if updated_order and updated_order.state == OrderState.FILLED:
            _update_intent_status(intent_id, IntentStatus.FILLED, conn)
        _write_executed_action(fill, intent, conn)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return ExecutionResult(
        intent_id=intent_id,
        decision="APPROVED",
        order_id=order.order_id,
        fill=fill,
        risk_decision=risk_decision,
        elapsed_ms=elapsed_ms,
    )


def process_new_intents(account_id: str, conn: sqlite3.Connection) -> list[ExecutionResult]:
    """Process all PENDING intents for the account (0199)."""
    rows = conn.execute(
        "SELECT intent_id FROM trade_intents WHERE account_id=? AND status='PENDING'",
        (account_id,),
    ).fetchall()
    results = []
    for row in rows:
        try:
            result = process_intent(row["intent_id"], conn)
            results.append(result)
        except Exception as exc:
            _log.error("process_intent failed for %s: %s", row["intent_id"], exc)
    return results


def process_open_orders(account_id: str, conn: sqlite3.Connection) -> list[Fill]:
    """Re-attempt fills on all WORKING/PARTIALLY_FILLED orders (0199).

    MtM refresh is done by run_execution_cycle() before this is called (0210).
    Syncs intent status when orders reach terminal states.
    """
    open_rows = conn.execute(
        """SELECT o.order_id, o.intent_id
           FROM orders o
           WHERE o.account_id=? AND o.state IN ('WORKING','PARTIALLY_FILLED')""",
        (account_id,),
    ).fetchall()

    broker = ShadowBroker(conn)
    fills: list[Fill] = []

    for row in open_rows:
        order = broker.get_order(row["order_id"])
        if not order:
            continue
        intent_row = conn.execute(
            "SELECT * FROM trade_intents WHERE intent_id=?", (row["intent_id"],)
        ).fetchone()
        if not intent_row:
            continue
        intent = TradeIntent.from_db_row(intent_row)

        quote = _get_quote(order.symbol)
        if not quote:
            conn.execute(
                "UPDATE orders SET market_data_status='unavailable' WHERE order_id=?",
                (order.order_id,),
            )
            conn.commit()
            continue

        conn.execute(
            "UPDATE orders SET market_data_status='ok' WHERE order_id=?",
            (order.order_id,),
        )

        fill = broker.attempt_fill(order, quote)

        if fill:
            fills.append(fill)
            _write_executed_action(fill, intent, conn)

        # Reload order to get current state after attempt
        updated = broker.get_order(order.order_id)
        if updated:
            _sync_intent_from_order(updated, row["intent_id"], conn)

    return fills


def run_execution_cycle(account_id: str, conn: sqlite3.Connection) -> dict:
    """Full execution cycle: refresh MtM → risk on fresh state → fill retry (0199, 0210).

    Order:
    1. _refresh_market_prices   — fresh MtM before any risk evaluation
    2. _update_nav_high_water   — update peak NAV
    3. _write_account_snapshot  — pre-cycle state
    4. process_new_intents      — PENDING intents evaluated against fresh marks
    5. count working_orders     — snapshot open-order count before retry
    6. process_open_orders      — retry open orders (no re-refresh inside)
    7. _write_account_snapshot  — post-cycle state
    """
    try:
        _refresh_market_prices(account_id, conn)
        _update_nav_high_water(account_id, conn)
    except Exception as exc:
        _log.warning("MtM refresh failed for %s: %s", account_id, exc)

    try:
        _write_account_snapshot(account_id, conn, "pre_cycle")
    except Exception as exc:
        _log.warning("pre-cycle snapshot failed: %s", exc)

    new_results = process_new_intents(account_id, conn)

    working_orders_checked = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')",
        (account_id,),
    ).fetchone()[0]

    retry_fills = process_open_orders(account_id, conn)

    try:
        _write_account_snapshot(account_id, conn, "post_cycle")
    except Exception as exc:
        _log.warning("post-cycle snapshot failed: %s", exc)

    return {
        "new_intents_processed": len(new_results),
        "open_orders_fills": len(retry_fills),
        "working_orders_checked": working_orders_checked,
        "results": [r.to_dict() for r in new_results],
    }


def run_pending_intents(account_id: str, conn: sqlite3.Connection) -> list[ExecutionResult]:
    """Deprecated: use run_execution_cycle(). Kept for backward compat."""
    run_execution_cycle(account_id, conn)
    return []
