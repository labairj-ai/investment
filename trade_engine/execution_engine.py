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
from enum import Enum
from typing import Optional

from .broker_adapter import BrokerAdapter, ShadowBrokerAdapter
from .broker_types import BrokerQuote
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
from .shadow_broker import Quote
from .market_data import _get_quote, _get_executable_quote, _get_mark_price

_log = logging.getLogger(__name__)


class TradingReadyState(str, Enum):
    """Startup readiness gate — ExecutionEngine must reach TRADING_READY before submitting orders (0242)."""
    INITIALIZING = "INITIALIZING"
    RECONCILING = "RECONCILING"
    TRADING_READY = "TRADING_READY"
    HALTED = "HALTED"


class PolicyUnavailable(RuntimeError):
    """Trading policy cannot be loaded; cycle must halt fail-closed (0227)."""


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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
    """Keep intent status in sync with order terminal states (0236).

    CANCELLED maps to IntentStatus.CANCELLED (not EXPIRED) — the two are distinct:
      EXPIRED = time-based expiry only (4pm DAY order, valid_until passed)
      CANCELLED = risk policy block, user request, reconciliation failure, etc.
    """
    _TERMINAL_MAP = {
        OrderState.FILLED: IntentStatus.FILLED,
        OrderState.CANCELLED: IntentStatus.CANCELLED,    # 0236: was EXPIRED, now CANCELLED
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


def _is_quote_fresh(
    quote: Quote,
    stale_minutes: int,
    *,
    require_market_timestamp: bool = False,
) -> bool:
    """Return True only when quote timestamps confirm fresh market data (0222, 0232, 0235).

    Checks market_timestamp first (exchange observation time). Falls back to retrieved_at
    only when market_timestamp is absent AND require_market_timestamp is False (shadow/yfinance).

    require_market_timestamp=True (paper/live adapters): market_timestamp must be present
    and fresh; retrieved_at alone is not sufficient for real-money execution (0235).

    Missing or unparseable timestamps always return False — fail closed.
    """
    now_ts = _now_utc().timestamp()
    if quote.market_timestamp:
        try:
            mt_ts = datetime.fromisoformat(
                quote.market_timestamp.replace("Z", "+00:00")
            ).timestamp()
            if (now_ts - mt_ts) / 60 > stale_minutes:
                return False  # market observation is too old
        except Exception:
            return False  # unparseable market_timestamp → fail closed (0232)
    elif require_market_timestamp:
        return False  # broker quotes must have exchange observation time (0235)
    # Require retrieved_at; absent means no provenance → fail closed (0232)
    if not quote.retrieved_at:
        return False
    try:
        rt_ts = datetime.fromisoformat(
            quote.retrieved_at.replace("Z", "+00:00")
        ).timestamp()
        return (now_ts - rt_ts) / 60 <= stale_minutes
    except Exception:
        return False


def _refresh_market_prices(account_id: str, conn: sqlite3.Connection) -> None:
    """Update market_price/market_value on position_snapshots using mark price (0201, 0222, 0232).

    Uses _get_quote() which allows last-price fallback — suitable for marking but NOT execution.
    Writes price_as_of = market_timestamp (when market observed the price) when available,
    otherwise falls back to retrieved_at. Silently skips symbols where price is unavailable.
    """
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
        # price_as_of = when market last observed this price, not when we fetched it (0232)
        price_as_of = quote.market_timestamp or quote.retrieved_at or _now_utc().isoformat()
        conn.execute(
            """UPDATE position_snapshots
               SET market_price=?, market_value=qty*?, price_as_of=?
               WHERE account_id=? AND symbol=?""",
            (mid, mid, price_as_of, account_id, symbol),
        )
    conn.commit()


def _check_portfolio_mark_freshness(
    account_id: str,
    conn: sqlite3.Connection,
    stale_minutes: int,
) -> tuple[bool, list[str]]:
    """Check whether all held positions have fresh market price marks (0221, 0228).

    Returns (is_fresh, stale_symbols). Unknown price is not safer than stale:
    any position with market_price IS NULL, price_as_of missing, or mark older
    than stale_minutes is considered stale. Called before authorizing new intents.
    """
    rows = conn.execute(
        "SELECT symbol, market_price, price_as_of FROM position_snapshots WHERE account_id=?",
        (account_id,),
    ).fetchall()
    now_ts = _now_utc().timestamp()
    stale: list[str] = []
    for r in rows:
        keys = r.keys()
        market_price = r["market_price"] if "market_price" in keys else None
        if market_price is None:
            stale.append(r["symbol"])  # unpriced = unknown = block (0228)
            continue
        price_as_of = r["price_as_of"] if "price_as_of" in keys else None
        if not price_as_of:
            stale.append(r["symbol"])
            continue
        try:
            ts = datetime.fromisoformat(price_as_of.replace("Z", "+00:00")).timestamp()
            if (now_ts - ts) / 60 > stale_minutes:
                stale.append(r["symbol"])
        except Exception:
            stale.append(r["symbol"])
    return (len(stale) == 0, stale)


def _write_account_snapshot(
    account_id: str, conn: sqlite3.Connection, reason: str = "cycle"
) -> None:
    """Write a point-in-time account snapshot to account_snapshots (0214)."""
    from .risk_engine import _open_buy_notional as _obn, _open_sell_notional as _osn
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
    # reserved_cash = buy-side only (sells don't consume cash)
    # open_order_notional = gross outstanding (buy + sell) for exposure visibility (0233)
    reserved_cash = _obn(account_id, conn)
    open_order_notional = reserved_cash + _osn(account_id, conn)
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


def process_intent(
    intent_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
) -> ExecutionResult:
    """Run the full execution pipeline for a single PENDING intent (0238).

    broker: BrokerAdapter to use. Defaults to ShadowBrokerAdapter when None.
    Fail-closed on missing quote (0200): if get_quote() returns None, the order
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

    if broker is None:
        broker = ShadowBrokerAdapter(conn, intent.account_id)

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
    order = broker.submit_order(intent)

    # ── First fill attempt ────────────────────────────────────────────────────
    existing_fill_row = conn.execute(
        "SELECT * FROM fills WHERE order_id=?", (order.order_id,)
    ).fetchone()

    fill: Optional[Fill] = None
    if existing_fill_row:
        fill = Fill.from_db_row(existing_fill_row)
    elif order.state in (OrderState.WORKING, OrderState.PARTIALLY_FILLED):
        stale_minutes = policy.halt_on_data_stale_minutes()
        raw_quote = _get_executable_quote(intent.symbol)
        if raw_quote:
            bquote = BrokerQuote(bid=raw_quote.bid, ask=raw_quote.ask, symbol=intent.symbol,
                                 market_timestamp=raw_quote.market_timestamp,
                                 retrieved_at=raw_quote.retrieved_at, source=raw_quote.source)
            if _is_quote_fresh(bquote, stale_minutes,
                               require_market_timestamp=broker.requires_market_timestamp):
                fill = broker.attempt_fill(order, bquote)
            else:
                conn.execute(
                    "UPDATE orders SET market_data_status='stale' WHERE order_id=?",
                    (order.order_id,),
                )
                conn.commit()
        else:
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


def process_new_intents(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
) -> list[ExecutionResult]:
    """Process all PENDING intents for the account (0199)."""
    rows = conn.execute(
        "SELECT intent_id FROM trade_intents WHERE account_id=? AND status='PENDING'",
        (account_id,),
    ).fetchall()
    results = []
    for row in rows:
        try:
            result = process_intent(row["intent_id"], conn, broker=broker)
            results.append(result)
        except Exception as exc:
            _log.error("process_intent failed for %s: %s", row["intent_id"], exc)
    return results


def process_open_orders(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
) -> tuple[list[Fill], int, int]:
    """Re-attempt fills on all WORKING/PARTIALLY_FILLED orders (0199, 0220, 0238).

    broker: BrokerAdapter to use. Defaults to ShadowBrokerAdapter when None.
    Returns (fills, pre_fill_rejections, orders_expired).
    MtM refresh is done by run_execution_cycle() before this is called (0210).
    Pre-fill risk revalidation prevents fills on orders that violate current limits (0220).
    """
    open_rows = conn.execute(
        """SELECT o.order_id, o.intent_id
           FROM orders o
           WHERE o.account_id=? AND o.state IN ('WORKING','PARTIALLY_FILLED')""",
        (account_id,),
    ).fetchall()

    if broker is None:
        broker = ShadowBrokerAdapter(conn, account_id)

    fills: list[Fill] = []
    pre_fill_rejections = 0
    orders_expired = 0

    try:
        policy = load_policy(account_id)
        stale_minutes = policy.halt_on_data_stale_minutes()
    except Exception as exc:
        # No policy = no authority = no fills (0227)
        raise PolicyUnavailable(f"Cannot load policy for {account_id!r}: {exc}") from exc

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

        # ── Pre-fill risk revalidation (0220, 0229, 0230) ─────────────────────
        account = _load_account(account_id, conn)
        if account:
            remaining_qty = (order.quantity or 0.0) - (order.fill_qty or 0.0)
            pre_fill_decision = risk_evaluate(
                intent, policy, account, conn,
                exclude_order_id=order.order_id,
                phase="PRE_FILL",
                remaining_quantity=max(0.0, remaining_qty),
            )
            if pre_fill_decision.decision == "REJECTED":
                broker.cancel_order(order.order_id, reason="RISK_REVALIDATION_FAILED")
                cancelled = broker.get_order(order.order_id)
                if cancelled:
                    _sync_intent_from_order(cancelled, row["intent_id"], conn)
                pre_fill_rejections += 1
                continue

        raw_quote = _get_executable_quote(order.symbol)
        if not raw_quote:
            conn.execute(
                "UPDATE orders SET market_data_status='unavailable' WHERE order_id=?",
                (order.order_id,),
            )
            conn.commit()
            continue

        bquote = BrokerQuote(bid=raw_quote.bid, ask=raw_quote.ask, symbol=order.symbol,
                             market_timestamp=raw_quote.market_timestamp,
                             retrieved_at=raw_quote.retrieved_at, source=raw_quote.source)
        if not _is_quote_fresh(bquote, stale_minutes,
                               require_market_timestamp=broker.requires_market_timestamp):
            conn.execute(
                "UPDATE orders SET market_data_status='stale' WHERE order_id=?",
                (order.order_id,),
            )
            conn.commit()
            continue

        conn.execute(
            "UPDATE orders SET market_data_status='ok' WHERE order_id=?",
            (order.order_id,),
        )

        fill = broker.attempt_fill(order, bquote)

        if fill:
            fills.append(fill)
            _write_executed_action(fill, intent, conn)

        updated = broker.get_order(order.order_id)
        if updated:
            if updated.state == OrderState.EXPIRED:
                orders_expired += 1
            _sync_intent_from_order(updated, row["intent_id"], conn)

    return fills, pre_fill_rejections, orders_expired


def run_execution_cycle(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
    *,
    trading_state: TradingReadyState = TradingReadyState.TRADING_READY,
) -> dict:
    """Full execution cycle: refresh MtM → freshness gate → risk → fill retry (0199, 0210).

    Order:
    1. _refresh_market_prices   — fresh MtM using mark prices before any risk evaluation
    2. _update_nav_high_water   — update peak NAV
    3. _write_account_snapshot  — pre-cycle state
    4. freshness gate           — block new intent authorization if any mark is stale (0221)
    5. process_new_intents      — PENDING intents evaluated against fresh marks
    6. process_open_orders      — retry open orders with pre-fill risk revalidation (0220)
    7. _write_account_snapshot  — post-cycle state
    """
    if trading_state != TradingReadyState.TRADING_READY:
        return {
            "execution_state": "HALTED",
            "halt_reason": "NOT_TRADING_READY",
            "trading_state": trading_state.value,
            "new_intents_processed": 0,
            "new_intents_blocked": True,
            "stale_symbols": [],
            "market_state": "unknown",
            "new_orders_created": 0,
            "fills_on_submission": 0,
            "risk_rejections": 0,
            "working_orders_checked": 0,
            "fills_on_retry": 0,
            "total_fills": 0,
            "orders_expired": 0,
            "results": [],
        }

    _HALTED_BASE = {
        "execution_state": "HALTED",
        "new_intents_processed": 0,
        "new_intents_blocked": True,
        "stale_symbols": [],
        "market_state": "unknown",
        "new_orders_created": 0,
        "fills_on_submission": 0,
        "risk_rejections": 0,
        "working_orders_checked": 0,
        "fills_on_retry": 0,
        "total_fills": 0,
        "orders_expired": 0,
        "results": [],
    }

    try:
        policy = load_policy(account_id)
        stale_minutes = policy.halt_on_data_stale_minutes()
    except Exception as exc:
        _log.error("POLICY_UNAVAILABLE for %s: %s — halting cycle fail-closed", account_id, exc)
        return {**_HALTED_BASE, "halt_reason": "POLICY_UNAVAILABLE"}

    try:
        _refresh_market_prices(account_id, conn)
        _update_nav_high_water(account_id, conn)
    except Exception as exc:
        _log.warning("MtM refresh failed for %s: %s", account_id, exc)

    try:
        _write_account_snapshot(account_id, conn, "pre_cycle")
    except Exception as exc:
        _log.warning("pre-cycle snapshot failed: %s", exc)

    # ── Freshness gate (0221): block new authorizations if any position mark is stale ──
    fresh, stale_symbols = _check_portfolio_mark_freshness(account_id, conn, stale_minutes)
    new_results: list[ExecutionResult] = []
    new_intents_blocked = False

    if broker is None:
        broker = ShadowBrokerAdapter(conn, account_id)

    if not fresh:
        _log.warning(
            "Stale market marks for account %s (symbols: %s) — new intent authorization blocked",
            account_id, stale_symbols,
        )
        new_intents_blocked = True
    else:
        new_results = process_new_intents(account_id, conn, broker=broker)

    # Count open orders before retry (snapshot includes orders created this cycle)
    working_orders_checked = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')",
        (account_id,),
    ).fetchone()[0]

    try:
        retry_fills, pre_fill_rejections, orders_expired_retry = process_open_orders(
            account_id, conn, broker=broker
        )
    except PolicyUnavailable as exc:
        _log.error("POLICY_UNAVAILABLE in fill retry for %s: %s — halting cycle", account_id, exc)
        return {**_HALTED_BASE, "halt_reason": "POLICY_UNAVAILABLE"}  # 0234: any policy failure → HALTED

    try:
        _write_account_snapshot(account_id, conn, "post_cycle")
    except Exception as exc:
        _log.warning("post-cycle snapshot failed: %s", exc)

    fills_on_submission = sum(1 for r in new_results if r.fill is not None)
    risk_rejections_new = sum(1 for r in new_results if r.decision == "REJECTED")
    market_state = "stale" if new_intents_blocked else "fresh"

    return {
        "execution_state": "OK",
        "new_intents_processed": len(new_results),
        "new_intents_blocked": new_intents_blocked,
        "stale_symbols": stale_symbols,
        "market_state": market_state,
        "new_orders_created": sum(1 for r in new_results if r.order_id is not None),
        "fills_on_submission": fills_on_submission,
        "risk_rejections": risk_rejections_new + pre_fill_rejections,
        "working_orders_checked": working_orders_checked,
        "fills_on_retry": len(retry_fills),
        "total_fills": fills_on_submission + len(retry_fills),
        "orders_expired": orders_expired_retry,
        "results": [r.to_dict() for r in new_results],
    }


def initialize_trading_session(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
) -> TradingReadyState:
    """Startup reconciliation sequence before accepting new orders (0242).

    Sequence:
    1. Connect — verify broker reachable via get_broker_account()
    2. Retrieve positions, open orders, fills since last sync
    3. Import broker fills not yet in local DB (prevents duplicate submission on restart)
    4. Reconcile local state against broker
    5. Return TRADING_READY or HALTED

    For shadow mode, broker IS local state — reconciliation is always MATCH and
    this returns TRADING_READY immediately.
    """
    from .reconciliation import reconcile

    if broker is None:
        broker = ShadowBrokerAdapter(conn, account_id)

    # Step 1: verify broker connectivity
    try:
        broker.get_broker_account(account_id)
    except Exception as exc:
        _log.error("initialize_trading_session: broker unreachable for %s: %s", account_id, exc)
        return TradingReadyState.HALTED

    # Step 2-3: import fills since last sync (prevents duplicate order submission on restart)
    try:
        last_sync_row = conn.execute(
            "SELECT last_fill_synced_at FROM trading_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        last_sync = last_sync_row["last_fill_synced_at"] if last_sync_row else None
        broker_fills = broker.get_fills(account_id, since=last_sync)
        imported = 0
        for bf in broker_fills:
            existing = conn.execute(
                "SELECT fill_id FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
            ).fetchone()
            if not existing:
                try:
                    conn.execute(
                        """INSERT OR IGNORE INTO fills
                           (fill_id, order_id, account_id, symbol, side, qty, price,
                            fee, fill_source, filled_at)
                           VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (bf.broker_fill_id, bf.local_order_id or bf.broker_order_id,
                         account_id, bf.symbol, bf.side, bf.qty, bf.price,
                         bf.fee, "broker_import", bf.filled_at),
                    )
                    imported += 1
                except Exception:
                    pass
        if imported > 0:
            _log.info("initialize_trading_session: imported %d broker fills for %s", imported, account_id)
        now_iso = _now_utc().isoformat()
        conn.execute(
            "UPDATE trading_accounts SET last_fill_synced_at=? WHERE account_id=?",
            (now_iso, account_id),
        )
        conn.commit()
    except Exception as exc:
        _log.warning("initialize_trading_session: fill import failed for %s: %s", account_id, exc)

    # Step 4: reconcile
    try:
        result = reconcile(account_id, conn, broker)
    except Exception as exc:
        _log.error("initialize_trading_session: reconciliation error for %s: %s", account_id, exc)
        return TradingReadyState.HALTED

    if result.blocks_submission:
        _log.error(
            "initialize_trading_session: %d blocking discrepancies for %s — HALTED",
            sum(1 for d in result.discrepancies if d.kind.value in {"CASH_MISMATCH", "BROKER_MISSING", "STATE_MISMATCH"}),
            account_id,
        )
        for d in result.discrepancies:
            _log.error("  %s %s: local=%s broker=%s — %s", d.kind, d.subject, d.local_value, d.broker_value, d.detail)
        return TradingReadyState.HALTED

    _log.info("initialize_trading_session: %s is TRADING_READY", account_id)
    return TradingReadyState.TRADING_READY


def run_pending_intents(account_id: str, conn: sqlite3.Connection) -> list[ExecutionResult]:
    """Deprecated: use run_execution_cycle(). Kept for backward compat."""
    run_execution_cycle(account_id, conn)
    return []
