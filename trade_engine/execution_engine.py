"""ExecutionEngine: orchestrates Intent → Risk → Shadow → Fill → executed_actions (0196).

Cycle architecture (0199):
  run_execution_cycle()
    process_new_intents()  — PENDING intents only; risk evaluate + submit order
    process_open_orders()  — WORKING/PARTIALLY_FILLED orders; refresh MtM, attempt fills
"""
from __future__ import annotations

import logging
import math
import sqlite3
import time
import uuid as _uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional

from .broker_adapter import BrokerAdapter, ShadowBrokerAdapter
from .broker_types import BrokerFill
from .models import (
    ExecutionResult,
    Fill,
    IntentStatus,
    Order,
    OrderState,
    OrderType,
    Side,
    TimeInForce,
    TradeIntent,
    TradingAccount,
    _parse_iso,
)
from .policy import TradingPolicy, load_policy
from .risk_engine import evaluate as risk_evaluate
from .shadow_broker import Quote
from .market_data import _get_quote, _get_mark_price
from . import market_calendar

_log = logging.getLogger(__name__)


class TradingReadyState(str, Enum):
    """Startup readiness gate — ExecutionEngine must reach TRADING_READY before submitting orders (0242)."""
    INITIALIZING = "INITIALIZING"
    RECONCILING = "RECONCILING"
    TRADING_READY = "TRADING_READY"
    HALTED = "HALTED"


class FillResult(str, Enum):
    """Return value of apply_broker_fill() indicating whether the fill was newly applied (0252)."""
    APPLIED = "APPLIED"
    ALREADY_APPLIED = "ALREADY_APPLIED"
    APPLIED_EXTERNAL = "APPLIED_EXTERNAL"  # 0568: ingested economically; no local order chain


class BrokerStateIntegrityError(RuntimeError):
    """Base for all broker state integrity violations that require an account halt (0288).

    Any subclass escaping process_intent() or apply_broker_fill() must halt the cycle
    before the next intent is evaluated. Callers should catch this base class rather than
    listing individual subclasses, so newly added integrity errors are automatically halted.
    """


class UnknownFillError(BrokerStateIntegrityError):
    """apply_broker_fill() cannot match a fill to any local order — quarantine required (0261)."""


class OverfillError(BrokerStateIntegrityError):
    """Fill quantity exceeds order remaining quantity — broker reporting error (0262)."""


class ImpossibleSellError(BrokerStateIntegrityError):
    """Sell fill quantity exceeds locally held position — state corruption (0262)."""


class SessionNotReadyError(RuntimeError):
    """process_intent() or run_execution_cycle() called before successful initialize() (0262)."""


class BrokerAccountMismatch(RuntimeError):
    """Broker get_account_id() returned an ID that doesn't match expected_broker_account_id (0272).

    Raised (and caught → HALTED) during initialize_trading_session() so no order is
    ever submitted to the wrong account. Set expected_broker_account_id to None in
    trading_policy.json to opt out of the check (shadow/paper accounts without a real broker ID).
    """


class BrokerSubmissionIndeterminate(RuntimeError):
    """submit_order() raised a network error after PENDING_SUBMIT was durably written (0265).

    Broker acceptance is unknown. The account must halt until reconciliation confirms
    whether the broker received the order. Recovery path: run initialize_trading_session()
    which will either import the broker order (WORKING) or leave PENDING_SUBMIT for manual
    review, then re-evaluate.
    """


class BrokerSettlementIndeterminate(BrokerStateIntegrityError):
    """FILLED ACK received but authoritative fill economics could not be retrieved (0278).

    Raised when get_fills_for_order() fails or returns no fills after a FILLED ACK,
    or when the ACK carries an ERROR or unrecognized normalized_state (0280).
    New order submissions must halt until the account's economic state is synchronized
    via reconciliation. Open-order polling and fill reconciliation may continue.
    Recovery path: run initialize_trading_session() + run_reconciliation() to ingest
    authoritative fills, then resume.
    """


_FILL_REPLAY_WINDOW_MINUTES = 15   # look this far back when querying fills to catch late arrivals (0257)
_MAX_LIMIT_OVERAGE = 2.0           # reject LIMIT orders > 200% above ask (BUY) or < 200% below bid (SELL) (0251)


class PolicyUnavailable(RuntimeError):
    """Trading policy cannot be loaded; cycle must halt fail-closed (0227)."""


class BrokerFillInvalid(BrokerStateIntegrityError):
    """apply_broker_fill() received a fill that fails identity or economics validation (0286).

    Raised when any field in the fill does not match the resolved local order or violates
    numeric invariants (zero qty, negative price, NaN/Inf). The fill is rejected and no
    DB state is mutated; callers must halt new submissions until the discrepancy is resolved.
    """


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


def _spawn_trade_outcome(
    conn: sqlite3.Connection,
    fill_id: str,
    order_id: str,
    symbol: str,
    fill_price: float,
    fill_qty: float,
    fill_fee: float,
    filled_at: str,
) -> None:
    """Create an initial trade_outcomes row after a new fill is applied (0333).

    Looks up episode_id and recommendation action via the order→intent→recommendation chain.
    The daily labeler fills in return/alpha fields once horizons mature.
    """
    try:
        row = conn.execute(
            """SELECT ti.intent_id, ti.episode_id, ti.limit_price as intent_limit_price,
                      ti.side as intent_side, ti.decision_market_price,
                      r.action as rec_action
               FROM trade_intents ti
               JOIN orders o ON ti.intent_id = o.intent_id
               LEFT JOIN recommendations r ON ti.recommendation_id = r.id
               WHERE o.order_id = ?""",
            (order_id,),
        ).fetchone()
        intent_id = row["intent_id"] if row else None
        episode_id = row["episode_id"] if row and "episode_id" in row.keys() else None
        action = row["rec_action"] if row else None
        row_keys = row.keys() if row and hasattr(row, "keys") else []
        # 0339: limit_price as arrival_price proxy (best available at spawn time)
        intent_limit_price = float(row["intent_limit_price"]) if row and row["intent_limit_price"] else None
        arrival_price = intent_limit_price
        # 0350: decision_market_price is pre-slippage price at intent creation
        decision_market_price = float(row["decision_market_price"]) if row and "decision_market_price" in row_keys and row["decision_market_price"] else None

        # 0350: limit_variance = fill vs limit (fill-vs-limit, not true IS)
        limit_variance = None
        if intent_limit_price and intent_limit_price > 0:
            is_sell = (action or "").upper() in ("SELL", "EXIT", "TRIM")
            if is_sell:
                limit_variance = (intent_limit_price - fill_price) / intent_limit_price
            else:
                limit_variance = (fill_price - intent_limit_price) / intent_limit_price

        # 0350: true IS = fill vs decision_market_price when available
        if decision_market_price and decision_market_price > 0:
            is_sell = (action or "").upper() in ("SELL", "EXIT", "TRIM")
            if is_sell:
                arrival_price = decision_market_price
            else:
                arrival_price = decision_market_price

        from zoneinfo import ZoneInfo
        from datetime import datetime as _dt
        try:
            et_tz = ZoneInfo("America/New_York")
        except Exception:
            from datetime import timezone as _tz, timedelta as _td
            et_tz = _tz(_td(hours=-4))
        decision_date = _dt.now(et_tz).strftime("%Y-%m-%d")
        fill_date = filled_at[:10] if filled_at else decision_date

        conn.execute(
            """INSERT OR IGNORE INTO trade_outcomes
               (fill_id, intent_id, episode_id, ticker, action, decision_date,
                fill_date, fill_price, fill_qty, fill_fees, arrival_price,
                limit_variance, label_type, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (fill_id, intent_id, episode_id, symbol, action, decision_date,
             fill_date, fill_price, fill_qty, fill_fee, arrival_price,
             limit_variance, "EXECUTED_TRADE_RETURN", time.time()),
        )
    except Exception as e:
        print(f"[execution_engine] WARNING: failed to spawn trade_outcome for fill {fill_id}: {e}")


def _write_executed_action(fill: Fill, intent: TradeIntent, conn: sqlite3.Connection) -> None:
    """Write shadow fill to executed_actions for outcome evaluator integration."""
    # 0331: populate recommendation_action with the source recommendation's semantic
    # action (BUY/TRIM/EXIT) rather than the fill-side verb (BUY/SELL), so the
    # executed_actions ledger reflects intent rather than mechanics.
    rec_action: Optional[str] = None
    if intent.recommendation_id is not None:
        rec_row = conn.execute(
            "SELECT action FROM recommendations WHERE id=?",
            (intent.recommendation_id,),
        ).fetchone()
        if rec_row:
            rec_action = rec_row["action"]

    conn.execute(
        """INSERT OR IGNORE INTO executed_actions
           (recommendation_id, ticker, action, quantity, execution_price,
            execution_date, fees, notes, source, created_at, fill_id,
            recommendation_action)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            intent.recommendation_id,
            fill.symbol,
            fill.side.value,
            fill.qty,
            fill.price,
            fill.filled_at[:10],
            fill.fee,
            f"fill_source={fill.fill_source}",
            fill.fill_source,
            time.time(),
            fill.fill_id,
            rec_action,
        ),
    )
    conn.commit()


def _is_quote_fresh(
    quote,  # Quote or BrokerQuote — both have market_timestamp and retrieved_at
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
            mt_ts = _parse_iso(quote.market_timestamp).timestamp()
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
        rt_ts = _parse_iso(quote.retrieved_at).timestamp()
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
            ts = _parse_iso(price_as_of).timestamp()
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
    *,
    _progress: Optional["CycleProgress"] = None,
) -> ExecutionResult:
    """Run the full execution pipeline for a single PENDING intent (0238, 0251, 0253).

    broker: BrokerAdapter to use. Defaults to ShadowBrokerAdapter when None.
    Quote gate (0251): get_quote() runs BEFORE submit_order(). Unavailable or stale
    quote → QUOTE_UNAVAILABLE; wide spread or bad limit price → QUOTE_REJECTED.
    PENDING_SUBMIT (0253): local order row committed before any broker network call.
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

    # ── Quote gate — must pass before order submission (0251) ─────────────────
    stale_minutes = policy.halt_on_data_stale_minutes()
    bquote = broker.get_quote(intent.symbol)

    if not bquote or not _is_quote_fresh(
        bquote, stale_minutes, require_market_timestamp=broker.requires_market_timestamp
    ):
        return ExecutionResult(
            intent_id=intent_id,
            decision="QUOTE_UNAVAILABLE",
            order_id=None,
            fill=None,
            risk_decision=risk_decision,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # Quote sanity: reject malformed quotes before any spread or limit check (0262)
    if bquote.bid <= 0 or bquote.ask <= 0 or bquote.bid > bquote.ask:
        return ExecutionResult(
            intent_id=intent_id,
            decision="QUOTE_REJECTED",
            order_id=None,
            fill=None,
            risk_decision=risk_decision,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # Spread sanity: reject if ask spread is too wide for reliable execution
    spread_pct = (bquote.ask - bquote.bid) / bquote.ask * 100.0
    if spread_pct > policy.max_spread_pct():
            return ExecutionResult(
                intent_id=intent_id,
                decision="QUOTE_REJECTED",
                order_id=None,
                fill=None,
                risk_decision=risk_decision,
                elapsed_ms=int((time.monotonic() - t0) * 1000),
            )

    # Limit price sanity: reject obviously off-market limits (0251)
    if intent.order_type == OrderType.LIMIT and intent.limit_price is not None:
        if intent.side in (Side.BUY, Side.BUY_TO_CLOSE) and bquote.ask > 0:
            if intent.limit_price > bquote.ask * (1.0 + _MAX_LIMIT_OVERAGE):
                return ExecutionResult(
                    intent_id=intent_id,
                    decision="QUOTE_REJECTED",
                    order_id=None,
                    fill=None,
                    risk_decision=risk_decision,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                )
        elif intent.side in (Side.SELL, Side.SELL_TO_OPEN) and bquote.bid > 0:
            if intent.limit_price < bquote.bid * (1.0 - _MAX_LIMIT_OVERAGE):
                return ExecutionResult(
                    intent_id=intent_id,
                    decision="QUOTE_REJECTED",
                    order_id=None,
                    fill=None,
                    risk_decision=risk_decision,
                    elapsed_ms=int((time.monotonic() - t0) * 1000),
                )

    # ── Pre-persist PENDING_SUBMIT row before any broker network call (0253) ──
    client_order_id = f"{intent.account_id}:{intent_id}"
    pending_order_id = str(_uuid.uuid4())
    now_str = _now_utc().isoformat()
    if intent.time_in_force == TimeInForce.DAY:
        expires_at = market_calendar.next_market_close().astimezone(timezone.utc).isoformat()
    else:
        expires_at = intent.valid_until
    conn.execute(
        """INSERT OR IGNORE INTO orders
           (order_id, intent_id, account_id, symbol, side, quantity,
            contracts, order_type, limit_price, state, time_in_force,
            submitted_at, updated_at, fill_qty, fill_cash, expires_at, client_order_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            pending_order_id, intent_id, intent.account_id, intent.symbol,
            intent.side.value, intent.quantity, intent.contracts,
            intent.order_type.value, intent.limit_price,
            OrderState.PENDING_SUBMIT.value, intent.time_in_force.value,
            now_str, now_str, 0.0, 0.0, expires_at, client_order_id,
        ),
    )
    conn.commit()

    # Resolve actual local order_id: INSERT OR IGNORE may have been a no-op if an order
    # already exists for this intent (crash-restart scenario). Re-query by intent_id so
    # subsequent references point to the canonical row, not the unused pending_order_id.
    resolved_row = conn.execute(
        "SELECT order_id, state FROM orders WHERE intent_id=?", (intent_id,)
    ).fetchone()
    local_order_id = resolved_row["order_id"] if resolved_row else pending_order_id

    # If the canonical order is already in a terminal state (crash-restart re-run path),
    # skip resubmission entirely — the intent has already been executed.
    if resolved_row and resolved_row["state"] in ("FILLED", "CANCELLED", "REJECTED", "EXPIRED"):
        fill_row = conn.execute(
            "SELECT * FROM fills WHERE order_id=? ORDER BY filled_at DESC LIMIT 1",
            (local_order_id,),
        ).fetchone()
        existing_fill = Fill.from_db_row(fill_row) if fill_row else None
        return ExecutionResult(
            intent_id=intent_id,
            decision="APPROVED",
            order_id=local_order_id,
            fill=existing_fill,
            risk_decision=risk_decision,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )

    # ── Order submission (broker call after local row is durable) ─────────────
    if _progress is not None:
        _progress.orders_created += 1
    try:
        ack = broker.submit_order(intent, client_order_id=client_order_id)
    except (TimeoutError, OSError, ConnectionError) as exc:
        # PENDING_SUBMIT is durable; broker acceptance is unknown (0265).
        # Halt the account so no further intents are submitted until reconciliation resolves state.
        raise BrokerSubmissionIndeterminate(
            f"intent {intent_id}: {type(exc).__name__} raised by submit_order after PENDING_SUBMIT "
            f"written — broker acceptance unknown; halt until reconciliation"
        ) from exc

    # ── Attach broker_order_id and advance PENDING_SUBMIT → correct ACK state (0267, 0271) ──
    # Execution engine owns the local ledger; adapter owns the broker API response.
    # Respect normalized_state from the ACK — do not blindly assume WORKING (0271).
    now_str2 = _now_utc().isoformat()
    _ack_state = ack.normalized_state or "WORKING"

    if _ack_state == "REJECTED":
        conn.execute(
            "UPDATE orders SET broker_order_id=?, state='REJECTED', submitted_at=? WHERE order_id=?",
            (ack.broker_order_id, ack.accepted_at or now_str2, local_order_id),
        )
        conn.commit()
        _update_intent_status(intent_id, IntentStatus.REJECTED, conn)
        return ExecutionResult(
            intent_id=intent_id,
            decision="REJECTED",
            order_id=local_order_id,
            fill=None,
            risk_decision=risk_decision,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
    elif _ack_state == "PENDING":
        # Broker queued the order but hasn't activated it; set/keep PENDING_SUBMIT for reconciliation.
        conn.execute(
            "UPDATE orders SET broker_order_id=?, state='PENDING_SUBMIT', submitted_at=? WHERE order_id=?",
            (ack.broker_order_id, ack.accepted_at or now_str2, local_order_id),
        )
        conn.commit()
        return ExecutionResult(
            intent_id=intent_id,
            decision="APPROVED",
            order_id=local_order_id,
            fill=None,
            risk_decision=risk_decision,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
    elif _ack_state == "FILLED":
        # Broker filled immediately (e.g. market-at-open); retrieve authoritative fills (0273, 0278).
        # Never synthesize price/fee — use only what the broker reports.
        # Fail closed: if we cannot retrieve authoritative economics, halt new submissions.
        conn.execute(
            "UPDATE orders SET broker_order_id=?, state='WORKING', submitted_at=? WHERE order_id=?",
            (ack.broker_order_id, ack.accepted_at or now_str2, local_order_id),
        )
        conn.commit()
        try:
            broker_fills = broker.get_fills_for_order(ack.broker_order_id)
        except Exception as _sf_exc:
            raise BrokerSettlementIndeterminate(
                f"FILLED ACK for order {local_order_id} (broker {ack.broker_order_id}): "
                f"get_fills_for_order() raised {type(_sf_exc).__name__} — "
                f"halting new submissions until reconciliation"
            ) from _sf_exc
        if not broker_fills:
            raise BrokerSettlementIndeterminate(
                f"FILLED ACK for order {local_order_id} (broker {ack.broker_order_id}): "
                f"no authoritative fills returned — halting new submissions until reconciliation"
            )
        fill: Optional[Fill] = None
        for bf in broker_fills:
            _fr = apply_broker_fill(bf, intent.account_id, conn, broker=broker)
            fill_row = conn.execute(
                "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
            ).fetchone()
            if fill_row:
                _f = Fill.from_db_row(fill_row)
                if fill is None:
                    fill = _f
                if _progress is not None and _fr == FillResult.APPLIED:
                    _progress.submission_fills.append(_f)
        # Do NOT call _update_intent_status(...FILLED) — apply_broker_fill() already sets
        # intent status to FILLED when aggregate fill qty reaches order qty (0278).
        # Audit row is written atomically inside apply_broker_fill() (0293).
        return ExecutionResult(
            intent_id=intent_id,
            decision="APPROVED",
            order_id=local_order_id,
            fill=fill,
            risk_decision=risk_decision,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
    elif _ack_state == "PARTIALLY_FILLED":
        # Broker filled some shares immediately; remainder is still WORKING (0280, 0282).
        # Fail closed: if authoritative fills are unavailable, halt new submissions.
        conn.execute(
            "UPDATE orders SET broker_order_id=?, state='WORKING', submitted_at=? WHERE order_id=?",
            (ack.broker_order_id, ack.accepted_at or now_str2, local_order_id),
        )
        conn.commit()
        try:
            _pf_fills = broker.get_fills_for_order(ack.broker_order_id)
        except Exception as _pf_exc:
            raise BrokerSettlementIndeterminate(
                f"PARTIALLY_FILLED ACK for order {local_order_id} (broker {ack.broker_order_id}): "
                f"get_fills_for_order() raised {type(_pf_exc).__name__} — "
                f"halting new submissions until reconciliation"
            ) from _pf_exc
        if not _pf_fills:
            raise BrokerSettlementIndeterminate(
                f"PARTIALLY_FILLED ACK for order {local_order_id} (broker {ack.broker_order_id}): "
                f"no authoritative fills returned — halting new submissions until reconciliation"
            )
        fill: Optional[Fill] = None
        for bf in _pf_fills:
            _fr = apply_broker_fill(bf, intent.account_id, conn, broker=broker)
            fill_row = conn.execute(
                "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
            ).fetchone()
            if fill_row:
                _f = Fill.from_db_row(fill_row)
                if fill is None:
                    fill = _f
                if _progress is not None and _fr == FillResult.APPLIED:
                    _progress.submission_fills.append(_f)
        # Audit row is written atomically inside apply_broker_fill() (0293).
        return ExecutionResult(
            intent_id=intent_id,
            decision="APPROVED",
            order_id=local_order_id,
            fill=fill,
            risk_decision=risk_decision,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
    elif _ack_state in ("CANCELLED", "EXPIRED"):
        # Immediate terminal response from broker — write terminal state and update intent (0280).
        conn.execute(
            "UPDATE orders SET broker_order_id=?, state=?, submitted_at=? WHERE order_id=?",
            (ack.broker_order_id, _ack_state, ack.accepted_at or now_str2, local_order_id),
        )
        conn.commit()
        _terminal_intent_map = {"CANCELLED": IntentStatus.CANCELLED, "EXPIRED": IntentStatus.EXPIRED}
        _update_intent_status(intent_id, _terminal_intent_map[_ack_state], conn)
        return ExecutionResult(
            intent_id=intent_id,
            decision=_ack_state,
            order_id=local_order_id,
            fill=None,
            risk_decision=risk_decision,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
    elif _ack_state == "WORKING":
        # Broker accepted; order is live. Fills arrive asynchronously — do NOT drain
        # the account-wide event queue here (0292). sync_broker_state() owns event ingestion.
        conn.execute(
            "UPDATE orders SET broker_order_id=?, state='WORKING', submitted_at=? WHERE order_id=?",
            (ack.broker_order_id, ack.accepted_at or now_str2, local_order_id),
        )
        conn.commit()
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        return ExecutionResult(
            intent_id=intent_id,
            decision="APPROVED",
            order_id=local_order_id,
            fill=None,  # fills ingested by sync_broker_state() at next cycle start
            risk_decision=risk_decision,
            elapsed_ms=elapsed_ms,
        )
    else:
        # ERROR or unrecognized ACK state — fail closed; never silently assume WORKING (0280).
        raise BrokerSettlementIndeterminate(
            f"order {local_order_id}: unrecognized ACK normalized_state {_ack_state!r} "
            f"from broker — halting new submissions"
        )

def process_new_intents(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
    *,
    _progress: Optional["CycleProgress"] = None,
) -> list[ExecutionResult]:
    """Submit at most one PENDING intent per cycle, oldest-first (0292)."""
    rows = conn.execute(
        "SELECT intent_id FROM trade_intents WHERE account_id=? AND status='PENDING'"
        " ORDER BY created_at ASC LIMIT 1",
        (account_id,),
    ).fetchall()
    results = []
    for row in rows:
        try:
            result = process_intent(row["intent_id"], conn, broker=broker, _progress=_progress)
            results.append(result)
        except (BrokerSubmissionIndeterminate, BrokerStateIntegrityError):
            raise  # propagate — further intent processing must stop (0265, 0278, 0288)
        except Exception as exc:
            _log.error("process_intent failed for %s: %s", row["intent_id"], exc)
    return results


def process_open_orders(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
    *,
    _progress: Optional["CycleProgress"] = None,
) -> tuple[list[Fill], int, int]:
    """Re-attempt fills on all WORKING/PARTIALLY_FILLED/CANCEL_REQUESTED orders via broker event stream (0199, 0220, 0238, 0256, 0266).

    broker: BrokerAdapter to use. Defaults to ShadowBrokerAdapter when None.
    Returns (fills, pre_fill_rejections, orders_expired).
    MtM refresh is done by run_execution_cycle() before this is called (0210).
    Pre-fill risk revalidation prevents fills on orders that violate current limits (0220).
    Fills are driven by poll_order_events() rather than attempt_fill() (0256).
    """
    open_rows = conn.execute(
        """SELECT o.order_id, o.broker_order_id, o.intent_id
           FROM orders o
           WHERE o.account_id=? AND o.state IN ('WORKING','PARTIALLY_FILLED','CANCEL_REQUESTED')""",
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

    # ── Poll ONCE for all open orders (0259) ─────────────────────────────────
    # Broker events are authoritative; quote unavailability must never gate ingestion.
    all_events = broker.poll_order_events(account_id)

    # Re-key events by resolved LOCAL order_id (0263): a real-broker event may carry
    # only broker_order_id; resolve_local_order_id() finds the correct local PK.
    events_by_order: dict[str, list] = {}
    for _e in all_events:
        _local_id = resolve_local_order_id(
            _e.local_order_id, _e.broker_order_id,
            getattr(_e, "client_order_id", None), conn,
        )
        if _local_id:
            events_by_order.setdefault(_local_id, []).append(_e)
        else:
            raise BrokerSettlementIndeterminate(
                f"process_open_orders: cannot resolve event {_e.event_type} "
                f"for broker_order_id={_e.broker_order_id!r} — halting (0285)"
            )

    for row in open_rows:
        # Local PK for all DB operations; broker-native ID for all external adapter calls (0268)
        broker_oid = row["broker_order_id"] or row["order_id"]
        order = broker.get_order(broker_oid)
        if not order:
            raise BrokerSettlementIndeterminate(
                f"process_open_orders: locally-open order {broker_oid!r} "
                f"not found at broker — halting (0285)"
            )
        intent_row = conn.execute(
            "SELECT * FROM trade_intents WHERE intent_id=?", (row["intent_id"],)
        ).fetchone()
        if not intent_row:
            continue
        intent = TradeIntent.from_db_row(intent_row)

        # ── Ingest broker events first (authoritative; quote-independent) (0259, 0261) ─
        # Events from the broker are final facts. Process them before risk revalidation
        # so a FILLED order is never risk-cancelled and a CANCELLED order is not re-evaluated.
        local_order_id = row["order_id"]  # always use local PK for DB operations (0275)
        for event in events_by_order.get(local_order_id, []):
            if event.event_type in ("FILLED", "PARTIALLY_FILLED"):
                if event.broker_fill_id:
                    bf = BrokerFill(
                        broker_fill_id=event.broker_fill_id,
                        broker_order_id=event.broker_order_id,
                        symbol=order.symbol,
                        side=order.side,  # BrokerOrder.side is already str (0275)
                        qty=float(event.fill_qty),
                        price=float(event.fill_price),
                        filled_at=event.filled_at or _now_utc().isoformat(),
                        fee=float(event.fee),
                        local_order_id=event.local_order_id,
                        account_id=account_id,
                        client_order_id=getattr(event, "client_order_id", None),
                    )
                    _apply_result = apply_broker_fill(bf, account_id, conn, broker=broker)
                    fill_row = conn.execute(
                        "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
                    ).fetchone()
                    if fill_row:
                        fill = Fill.from_db_row(fill_row)
                        fills.append(fill)
                        if _progress is not None and _apply_result == FillResult.APPLIED:
                            _progress.retry_fills.append(fill)
                else:
                    # No broker_fill_id — do NOT invent one; fetch authoritative fills (0283).
                    try:
                        _auth_fills = broker.get_fills_for_order(event.broker_order_id)
                    except Exception as _af_exc:
                        raise BrokerSettlementIndeterminate(
                            f"fill event for order {local_order_id} has no broker_fill_id and "
                            f"get_fills_for_order() raised {type(_af_exc).__name__} — "
                            f"halting new submissions"
                        ) from _af_exc
                    if not _auth_fills:
                        raise BrokerSettlementIndeterminate(
                            f"fill event for order {local_order_id} has no broker_fill_id and "
                            f"get_fills_for_order() returned empty — halting new submissions"
                        )
                    for bf in _auth_fills:
                        _apply_result = apply_broker_fill(bf, account_id, conn, broker=broker)
                        fill_row = conn.execute(
                            "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
                        ).fetchone()
                        if fill_row:
                            fill = Fill.from_db_row(fill_row)
                            fills.append(fill)
                            if _progress is not None and _apply_result == FillResult.APPLIED:
                                _progress.retry_fills.append(fill)
            elif event.event_type in ("CANCELLED", "EXPIRED", "REJECTED"):
                apply_broker_order_event(event, account_id, conn)
            else:
                raise BrokerStateIntegrityError(
                    f"process_open_orders: unrecognized normalized event_type {event.event_type!r} "
                    f"for order {local_order_id} — adapter contract violation (0290)"
                )

        # Skip risk revalidation if the order is no longer open after event ingestion
        post_event_order = conn.execute(
            "SELECT state FROM orders WHERE order_id=?", (local_order_id,)
        ).fetchone()
        if post_event_order and post_event_order["state"] not in ("WORKING", "PARTIALLY_FILLED"):
            # Sync intent status from the terminal order state (handles ALREADY_APPLIED case
            # where shadow_broker._apply_fill() already wrote the fill to DB)
            terminal_order = broker.get_order(broker_oid)  # returns BrokerOrder (0275)
            if terminal_order:
                _sync_intent_from_order(terminal_order, row["intent_id"], conn)
            continue

        # ── Pre-fill risk revalidation (0220, 0229, 0230) ─────────────────────
        account = _load_account(account_id, conn)
        if account:
            remaining_qty = (order.quantity or 0.0) - (order.fill_qty or 0.0)
            pre_fill_decision = risk_evaluate(
                intent, policy, account, conn,
                exclude_order_id=local_order_id,
                phase="PRE_FILL",
                remaining_quantity=max(0.0, remaining_qty),
            )
            if pre_fill_decision.decision == "REJECTED":
                broker.cancel_order(broker_oid, reason="RISK_REVALIDATION_FAILED")  # broker-native ID (0268)
                cancelled = broker.get_order(broker_oid)
                if cancelled:
                    _sync_intent_from_order(cancelled, row["intent_id"], conn)
                pre_fill_rejections += 1
                if _progress is not None:
                    _progress.pre_fill_rejections += 1
                continue

        # ── Quote: update market_data_status; stale quote only blocks submissions ─
        bquote = broker.get_quote(order.symbol)
        if not bquote:
            conn.execute(
                "UPDATE orders SET market_data_status='unavailable' WHERE order_id=?",
                (local_order_id,),
            )
        elif not _is_quote_fresh(bquote, stale_minutes,
                                 require_market_timestamp=broker.requires_market_timestamp):
            conn.execute(
                "UPDATE orders SET market_data_status='stale' WHERE order_id=?",
                (local_order_id,),
            )
        else:
            conn.execute(
                "UPDATE orders SET market_data_status='ok' WHERE order_id=?",
                (local_order_id,),
            )
        conn.commit()

        updated = broker.get_order(broker_oid)  # returns BrokerOrder; broker-native ID (0268, 0275)
        if updated:
            if updated.state == "EXPIRED":
                orders_expired += 1
                if _progress is not None:
                    _progress.orders_expired += 1
            _sync_intent_from_order(updated, row["intent_id"], conn)

    return fills, pre_fill_rejections, orders_expired


def sync_broker_state(
    account_id: str,
    conn: sqlite3.Connection,
    broker: BrokerAdapter,
    *,
    _fill_stats: Optional[dict] = None,
    _progress: Optional["CycleProgress"] = None,
) -> tuple[list[Fill], int, dict]:
    """Ingest all pending broker events as the first action in a cycle (0284).

    Polls broker.poll_order_events() once and applies FILLED/PARTIALLY_FILLED events via
    apply_broker_fill() and CANCELLED/EXPIRED events via apply_broker_order_event().
    Called before process_new_intents() so fills arriving between cycles update local
    economic state before any risk evaluation occurs.

    Raises BrokerSettlementIndeterminate on unresolvable events (0285) or fill retrieval
    failures; callers treat this as HALTED. Returns (newly_applied_fills, duplicate_fills_skipped, stats).
    """
    _seen_ids: set[str] = set()
    _new_ids: set[str] = set()
    if _fill_stats is not None:
        _fill_stats.update(seen_ids=_seen_ids, new_ids=_new_ids)

    def observe(fill):
        if fill.broker_fill_id:
            _seen_ids.add(fill.broker_fill_id)
        result = apply_broker_fill(fill, account_id, conn, broker=broker)
        if result in (FillResult.APPLIED, FillResult.APPLIED_EXTERNAL) and fill.broker_fill_id:
            _new_ids.add(fill.broker_fill_id)
        return result

    all_events = broker.poll_order_events(account_id)
    fills: list[Fill] = []
    duplicate_fills_skipped: int = 0

    for _e in all_events:
        _local_id = resolve_local_order_id(
            _e.local_order_id, _e.broker_order_id,
            getattr(_e, "client_order_id", None), conn,
        )
        if _local_id is None:
            raise BrokerSettlementIndeterminate(
                f"sync_broker_state: cannot resolve event {_e.event_type} "
                f"for broker_order_id={_e.broker_order_id!r} — halting (0285)"
            )

        if _e.event_type in ("FILLED", "PARTIALLY_FILLED"):
            _order_meta = conn.execute(
                "SELECT symbol, side, intent_id FROM orders WHERE order_id=?", (_local_id,)
            ).fetchone()
            if _order_meta is None:
                raise BrokerSettlementIndeterminate(
                    f"sync_broker_state: resolved order {_local_id!r} not found in DB — halting"
                )

            if _e.broker_fill_id:
                _bf = BrokerFill(
                    broker_fill_id=_e.broker_fill_id,
                    broker_order_id=_e.broker_order_id,
                    symbol=_order_meta["symbol"],
                    side=_order_meta["side"],
                    qty=float(_e.fill_qty),
                    price=float(_e.fill_price),
                    filled_at=_e.filled_at or _now_utc().isoformat(),
                    fee=float(_e.fee),
                    local_order_id=_e.local_order_id,
                    account_id=account_id,
                    client_order_id=getattr(_e, "client_order_id", None),
                )
                _result = observe(_bf)
                if _result == FillResult.APPLIED:
                    _fill_row = conn.execute(
                        "SELECT * FROM fills WHERE fill_id=?", (_bf.broker_fill_id,)
                    ).fetchone()
                    if _fill_row:
                        _fill = Fill.from_db_row(_fill_row)
                        fills.append(_fill)
                        if _progress is not None:
                            _progress.sync_fills.append(_fill)
                else:
                    duplicate_fills_skipped += 1
                    if _progress is not None:
                        _progress.duplicate_fills_skipped += 1
            else:
                # No broker_fill_id — fetch authoritative fills (0283)
                try:
                    _auth_fills = broker.get_fills_for_order(_e.broker_order_id)
                except Exception as _af_exc:
                    raise BrokerSettlementIndeterminate(
                        f"sync_broker_state: fill event for order {_local_id} has no broker_fill_id and "
                        f"get_fills_for_order() raised {type(_af_exc).__name__} — halting"
                    ) from _af_exc
                if not _auth_fills:
                    raise BrokerSettlementIndeterminate(
                        f"sync_broker_state: fill event for order {_local_id} has no broker_fill_id and "
                        f"get_fills_for_order() returned empty — halting"
                    )
                for _bf in _auth_fills:
                    _result = observe(_bf)
                    if _result == FillResult.APPLIED:
                        _fill_row = conn.execute(
                            "SELECT * FROM fills WHERE fill_id=?", (_bf.broker_fill_id,)
                        ).fetchone()
                        if _fill_row:
                            _fill = Fill.from_db_row(_fill_row)
                            fills.append(_fill)
                            if _progress is not None:
                                _progress.sync_fills.append(_fill)
                    else:
                        duplicate_fills_skipped += 1
                        if _progress is not None:
                            _progress.duplicate_fills_skipped += 1

        elif _e.event_type in ("CANCELLED", "EXPIRED", "REJECTED"):
            apply_broker_order_event(_e, account_id, conn)
        else:
            raise BrokerStateIntegrityError(
                f"sync_broker_state: unrecognized normalized event_type {_e.event_type!r} "
                f"for order_id={_local_id!r} — adapter contract violation (0290)"
            )

    # ── Ledger pull: catch fills missed by the push event queue (0289) ─────────
    # poll_order_events() depends on the broker's WebSocket push. A dropped connection
    # or delayed event silently misses a fill. Querying the broker's authoritative fill
    # log on every cycle with the same cursor+replay-window used by
    # initialize_trading_session() ensures any missed fill is ingested before the next
    # risk evaluation. apply_broker_fill() is idempotent — already-applied fills are
    # skipped with FillResult.ALREADY_APPLIED.
    try:
        _ls_row = conn.execute(
            "SELECT last_fill_synced_at FROM trading_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        _last_sync_ts = _ls_row["last_fill_synced_at"] if _ls_row else None
        _since: Optional[str] = (
            (_parse_iso(_last_sync_ts) - timedelta(minutes=_FILL_REPLAY_WINDOW_MINUTES)).isoformat()
            if _last_sync_ts else None
        )
        _ledger = broker.get_fills(account_id, since=_since)
        _max_filled_at: Optional[str] = None
        for _lf in _ledger:
            _lr = observe(_lf)
            if _lr == FillResult.APPLIED:
                _fill_row = conn.execute(
                    "SELECT * FROM fills WHERE fill_id=?", (_lf.broker_fill_id,)
                ).fetchone()
                if _fill_row:
                    _fill = Fill.from_db_row(_fill_row)
                    fills.append(_fill)
                    if _progress is not None:
                        _progress.sync_fills.append(_fill)
            elif _lr == FillResult.ALREADY_APPLIED:
                duplicate_fills_skipped += 1
                if _progress is not None:
                    _progress.duplicate_fills_skipped += 1
            # 0567: advance cursor for all observed fills regardless of APPLIED/ALREADY_APPLIED
            if _lf.filled_at and (_max_filled_at is None or _lf.filled_at > _max_filled_at):
                _max_filled_at = _lf.filled_at
        if _max_filled_at:
            conn.execute(
                "UPDATE trading_accounts SET last_fill_synced_at=? WHERE account_id=?",
                (_max_filled_at, account_id),
            )
            conn.commit()
    except BrokerStateIntegrityError:
        raise  # fill validation failures must still halt
    except Exception as _ledger_exc:
        raise BrokerSettlementIndeterminate(
            f"sync_broker_state: ledger fill pull failed for {account_id}: "
            f"{type(_ledger_exc).__name__} — halting (0289)"
        ) from _ledger_exc

    _broker_stats = _merge_invocation_broker_stats({}, {
        "_seen_ids": _seen_ids, "_new_ids": _new_ids,
    }, conn)
    _broker_stats.update(_seen_ids=_seen_ids, _new_ids=_new_ids)
    return fills, duplicate_fills_skipped, _broker_stats


@dataclass
class CycleProgress:
    """Accumulates in-progress cycle activity so every exit path reports what actually happened (0577).

    Each stage updates this object as events occur. run_execution_cycle() calls to_summary() on
    every exit path — HALTED or OK — so no activity is silently erased by a later-stage failure.
    """
    # sync stage
    sync_fills: list = field(default_factory=list)
    duplicate_fills_skipped: int = 0
    broker_fills_observed: int = 0
    broker_fills_new: int = 0
    broker_fills_duplicate: int = 0
    external_fills_observed: int = 0
    broker_seen_ids: set = field(default_factory=set)
    broker_new_ids: set = field(default_factory=set)
    # freshness gate (defaults match pre-gate HALT semantics)
    new_intents_blocked: bool = True
    stale_symbols: list = field(default_factory=list)
    market_state: str = "unknown"
    # intent stage
    new_results: list = field(default_factory=list)
    orders_created: int = 0
    submission_fills: list = field(default_factory=list)
    working_orders_checked: int = 0
    # open-order stage — updated per-order inside process_open_orders()
    retry_fills: list = field(default_factory=list)
    pre_fill_rejections: int = 0
    orders_expired: int = 0

    def to_summary(self, execution_state: str, halt_reason: str | None = None) -> dict:
        fills_on_submission = len(self.submission_fills)
        risk_rejections_new = sum(1 for r in self.new_results if r.decision == "REJECTED")
        d = {
            "execution_state": execution_state,
            "new_intents_processed": len(self.new_results),
            "new_intents_blocked": self.new_intents_blocked,
            "stale_symbols": self.stale_symbols,
            "market_state": self.market_state,
            "new_orders_created": self.orders_created,
            "fills_on_sync": len(self.sync_fills),
            "fills_on_submission": fills_on_submission,
            "risk_rejections": risk_rejections_new + self.pre_fill_rejections,
            "working_orders_checked": self.working_orders_checked,
            "fills_on_retry": len(self.retry_fills),
            "total_fills": len(self.sync_fills) + fills_on_submission + len(self.retry_fills),
            "orders_expired": self.orders_expired,
            "duplicate_fills_skipped": self.duplicate_fills_skipped,
            "broker_fills_observed": self.broker_fills_observed,
            "broker_fills_new": self.broker_fills_new,
            "broker_fills_duplicate": self.broker_fills_duplicate,
            "external_fills_observed": self.external_fills_observed,
            "_seen_ids": self.broker_seen_ids,
            "_new_ids": self.broker_new_ids,
            "results": [r.to_dict() for r in self.new_results],
        }
        if halt_reason is not None:
            d["halt_reason"] = halt_reason
        return d


def run_execution_cycle(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
    *,
    trading_state: TradingReadyState = TradingReadyState.INITIALIZING,  # (0244) callers must earn TRADING_READY
) -> dict:
    """Full execution cycle: broker sync → refresh MtM → freshness gate → risk → fill retry (0199, 0210, 0284).

    Order:
    1. sync_broker_state    — ingest pending fills/events before any risk evaluation (0284)
    2. _refresh_market_prices   — fresh MtM using mark prices before any risk evaluation
    3. _update_nav_high_water   — update peak NAV
    4. _write_account_snapshot  — pre-cycle state
    5. freshness gate           — block new intent authorization if any mark is stale (0221)
    6. process_new_intents      — PENDING intents evaluated against fresh marks
    7. process_open_orders      — retry open orders with pre-fill risk revalidation (0220)
    8. _write_account_snapshot  — post-cycle state
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
            "fills_on_sync": 0,
            "fills_on_submission": 0,
            "risk_rejections": 0,
            "working_orders_checked": 0,
            "fills_on_retry": 0,
            "total_fills": 0,
            "orders_expired": 0,
            "duplicate_fills_skipped": 0,
            "broker_fills_observed": 0,
            "broker_fills_new": 0,
            "broker_fills_duplicate": 0,
            "external_fills_observed": 0,
            "results": [],
        }

    # 0577: progress accumulator — every exit path calls progress.to_summary() so no
    # activity committed before a later-stage halt is silently erased from the summary.
    progress = CycleProgress()

    try:
        policy = load_policy(account_id)
        stale_minutes = policy.halt_on_data_stale_minutes()
    except Exception as exc:
        _log.error("POLICY_UNAVAILABLE for %s: %s — halting cycle fail-closed", account_id, exc)
        return progress.to_summary("HALTED", "POLICY_UNAVAILABLE")

    if broker is None:
        broker = ShadowBrokerAdapter(conn, account_id)

    # ── 0284: Broker truth sync — ingest all pending fills before risk evaluation ─
    sync_stats: dict = {}
    try:
        sync_fills, duplicate_fills_skipped, broker_stats = sync_broker_state(
            account_id, conn, broker, _fill_stats=sync_stats, _progress=progress)
    except BrokerStateIntegrityError as exc:
        _log.error(
            "BROKER_STATE_INTEGRITY in broker sync for %s: %s — halting cycle; reconcile before next run",
            account_id, exc,
        )
        result = _merge_invocation_broker_stats(sync_stats, {
            **progress.to_summary("HALTED", "BROKER_STATE_INTEGRITY"),
        }, conn)
        result.update(_seen_ids=sync_stats.get("seen_ids", set()),
                      _new_ids=sync_stats.get("new_ids", set()))
        return result

    progress.broker_fills_observed = broker_stats.get("broker_fills_observed", 0)
    progress.broker_fills_new = broker_stats.get("broker_fills_new", 0)
    progress.broker_fills_duplicate = broker_stats.get("broker_fills_duplicate", 0)
    progress.external_fills_observed = broker_stats.get("external_fills_observed", 0)
    progress.broker_seen_ids = broker_stats.get("_seen_ids", set())
    progress.broker_new_ids = broker_stats.get("_new_ids", set())

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
    progress.stale_symbols = stale_symbols

    if not fresh:
        _log.warning(
            "Stale market marks for account %s (symbols: %s) — new intent authorization blocked",
            account_id, stale_symbols,
        )
        progress.new_intents_blocked = True
        progress.market_state = "stale"
    else:
        progress.new_intents_blocked = False
        progress.market_state = "fresh"
        try:
            progress.new_results = process_new_intents(account_id, conn, broker=broker, _progress=progress)
        except BrokerSubmissionIndeterminate as exc:
            _log.error(
                "SUBMISSION_INDETERMINATE for %s: %s — halting cycle; reconcile before next run",
                account_id, exc,
            )
            return progress.to_summary("HALTED", "SUBMISSION_INDETERMINATE")
        except BrokerStateIntegrityError as exc:
            _log.error(
                "BROKER_STATE_INTEGRITY for %s: %s — halting cycle; reconcile before next run",
                account_id, exc,
            )
            return progress.to_summary("HALTED", "BROKER_STATE_INTEGRITY")

    # Count open orders before retry (snapshot includes orders created this cycle)
    progress.working_orders_checked = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')",
        (account_id,),
    ).fetchone()[0]

    try:
        process_open_orders(account_id, conn, broker=broker, _progress=progress)
    except PolicyUnavailable as exc:
        _log.error("POLICY_UNAVAILABLE in fill retry for %s: %s — halting cycle", account_id, exc)
        return progress.to_summary("HALTED", "POLICY_UNAVAILABLE")  # 0234: any policy failure → HALTED
    except BrokerStateIntegrityError as exc:
        _log.error(
            "BROKER_STATE_INTEGRITY in fill retry for %s: %s — halting cycle; reconcile before next run",
            account_id, exc,
        )
        return progress.to_summary("HALTED", "BROKER_STATE_INTEGRITY")

    try:
        _write_account_snapshot(account_id, conn, "post_cycle")
    except Exception as exc:
        _log.warning("post-cycle snapshot failed: %s", exc)

    return progress.to_summary("OK")


def _merge_invocation_broker_stats(
    init_fill_stats: dict,
    cycle_result: dict,
    conn: sqlite3.Connection,
) -> dict:
    """Merge fill tracking from initialize() and run_cycle() into runner-invocation-level stats (0571).

    Deduplicates by broker_fill_id across both phases so a fill first seen in initialize()
    and then observed again (ALREADY_APPLIED) in the ledger pull is counted once as new,
    not as duplicate. external_fills_observed is based on the persisted fills.origin column.
    """
    result = dict(cycle_result)
    cycle_seen: set[str] = result.pop("_seen_ids", set())
    cycle_new: set[str] = result.pop("_new_ids", set())

    all_seen = init_fill_stats.get("seen_ids", set()) | cycle_seen
    all_new = init_fill_stats.get("new_ids", set()) | cycle_new
    # A quarantined observation is neither new nor a previously persisted duplicate.
    persisted = []
    if all_seen:
        placeholders = ",".join("?" * len(all_seen))
        persisted = conn.execute(
            f"SELECT fill_id, origin FROM fills WHERE fill_id IN ({placeholders})",
            list(all_seen),
        ).fetchall()
    all_dup = {r[0] for r in persisted} - all_new
    ext_count = sum(r[1] != 'ENGINE' for r in persisted)

    result["broker_fills_observed"] = len(all_seen)
    result["broker_fills_new"] = len(all_new)
    result["broker_fills_duplicate"] = len(all_dup)
    result["external_fills_observed"] = ext_count
    return result


class ExecutionSession:
    """Execution context that owns initialization state so TRADING_READY is never caller-supplied (0262).

    Usage:
        session = ExecutionSession(account_id, conn, broker)
        session.initialize()                # reconciliation; raises SessionNotReadyError if not READY
        session.process_intent(intent_id)
        session.run_cycle()
    """

    def __init__(
        self,
        account_id: str,
        conn: sqlite3.Connection,
        broker: Optional[BrokerAdapter] = None,
    ) -> None:
        self._account_id = account_id
        self._conn = conn
        self._broker = broker
        self._initialized: bool = False
        self._trading_state: Optional[TradingReadyState] = None

    def initialize(self) -> TradingReadyState:
        """Run startup reconciliation. Raises SessionNotReadyError if result is not TRADING_READY."""
        self._init_fill_stats: dict = {}
        state = initialize_trading_session(
            self._account_id, self._conn, self._broker, _fill_stats=self._init_fill_stats
        )
        self._trading_state = state
        if state != TradingReadyState.TRADING_READY:
            raise SessionNotReadyError(
                f"initialize_trading_session returned {state.value} for {self._account_id}"
            )
        self._initialized = True
        return state

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise SessionNotReadyError(
                "ExecutionSession.initialize() must succeed before processing orders"
            )

    def process_intent(self, intent_id: int) -> "ExecutionResult":
        self._require_initialized()
        return process_intent(intent_id, self._conn, broker=self._broker)

    def process_open_orders(self) -> tuple:
        self._require_initialized()
        return process_open_orders(self._account_id, self._conn, broker=self._broker)

    def run_cycle(self) -> dict:
        self._require_initialized()
        result = run_execution_cycle(
            self._account_id,
            self._conn,
            broker=self._broker,
            trading_state=TradingReadyState.TRADING_READY,
        )
        return self.merge_broker_stats(result)

    def merge_broker_stats(self, result: dict) -> dict:
        """Finalize invocation telemetry even when initialization did not become ready."""
        return _merge_invocation_broker_stats(
            getattr(self, "_init_fill_stats", {}), result, self._conn
        )


def resolve_local_order_id(
    local_order_id: Optional[str],
    broker_order_id: Optional[str],
    client_order_id: Optional[str],
    conn: sqlite3.Connection,
) -> Optional[str]:
    """Return the local orders.order_id by trying three lookups in priority order (0263).

    Resolution order:
      1. local_order_id   — direct PK match (shadow mode; always set when engine created the order)
      2. broker_order_id  — match on orders.broker_order_id column (real-broker events)
      3. client_order_id  — match on orders.client_order_id column (reconciliation fallback)

    Returns None when no unique match is found. Callers should raise UnknownFillError /
    halt when None is returned.
    """
    if local_order_id:
        row = conn.execute(
            "SELECT order_id FROM orders WHERE order_id=?", (local_order_id,)
        ).fetchone()
        if row:
            return row["order_id"]

    if broker_order_id:
        row = conn.execute(
            "SELECT order_id FROM orders WHERE broker_order_id=?", (broker_order_id,)
        ).fetchone()
        if row:
            return row["order_id"]

    if client_order_id:
        rows = conn.execute(
            "SELECT order_id FROM orders WHERE client_order_id=?", (client_order_id,)
        ).fetchall()
        if len(rows) == 1:
            return rows[0]["order_id"]
        if len(rows) > 1:
            _log.warning(
                "resolve_local_order_id: multiple orders share client_order_id %r — cannot resolve uniquely",
                client_order_id,
            )

    return None


def apply_broker_fill(
    bf,  # BrokerFill
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
) -> FillResult:
    """Apply a broker fill atomically: fills + order state + positions + cash + audit (0245, 0252, 0261, 0262).

    Idempotent (0261): uses INSERT OR IGNORE + rowcount so concurrent callers both get a clean
    result (APPLIED or ALREADY_APPLIED) without exceptions. All mutations run in one
    transaction; conn.rollback() is called on any failure.

    Guards (0262):
    - UnknownFillError: fill cannot be matched to any local order → quarantine
    - OverfillError: fill qty exceeds order remaining quantity
    - ImpossibleSellError: sell qty exceeds held position
    """
    # ── Early dedup: if fill_id already recorded, skip before order resolution ──
    # Prevents quarantine of fills whose orders are no longer in the local DB
    # (prior integration test runs, pre-existing manual trades). Preserves the
    # 0293 audit-repair path by reading order_id from the existing fills row.
    if bf.broker_fill_id:
        _existing_fill = conn.execute(
            "SELECT order_id, fill_source, filled_at FROM fills WHERE fill_id=?",
            (bf.broker_fill_id,),
        ).fetchone()
        if _existing_fill:
            _stored_oid = _existing_fill["order_id"]
            _ea_missing = not conn.execute(
                "SELECT 1 FROM executed_actions WHERE fill_id=?", (bf.broker_fill_id,)
            ).fetchone()
            if _ea_missing and _stored_oid:
                _ir2 = conn.execute(
                    """SELECT ti.recommendation_id FROM trade_intents ti
                       JOIN orders o ON ti.intent_id = o.intent_id
                       WHERE o.order_id = ?""",
                    (_stored_oid,),
                ).fetchone()
                _fsrc = _existing_fill["fill_source"] or "broker_import"
                _fat = _existing_fill["filled_at"] or bf.filled_at
                conn.execute(
                    """INSERT OR IGNORE INTO executed_actions
                       (recommendation_id, ticker, action, quantity, execution_price,
                        execution_date, fees, notes, source, created_at, fill_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _ir2["recommendation_id"] if _ir2 else None,
                        bf.symbol, bf.side, float(bf.qty), float(bf.price),
                        _fat[:10] if _fat else None,
                        float(bf.fee), f"fill_source={_fsrc}", _fsrc,
                        time.time(), bf.broker_fill_id,
                    ),
                )
            # 0571: reconciled_at advances on every successful broker observation
            conn.execute(
                "UPDATE fills SET reconciled_at=? WHERE fill_id=?",
                (_now_utc().isoformat(), bf.broker_fill_id),
            )
            conn.commit()
            return FillResult.ALREADY_APPLIED

    # Resolve local order_id via the three-tier identity resolver (0263)
    order_id = resolve_local_order_id(
        bf.local_order_id, bf.broker_order_id, getattr(bf, "client_order_id", None), conn
    )
    if order_id is None:
        # An absent local mapping is not proof of external ownership (0572).
        if broker is None or not bf.broker_order_id:
            raise UnknownFillError(f"fill {bf.broker_fill_id}: broker ownership lookup required")
        try:
            owner = broker.get_order(bf.broker_order_id)
        except Exception as exc:
            raise BrokerSettlementIndeterminate(
                f"fill {bf.broker_fill_id}: broker ownership lookup unavailable — quarantine"
            ) from exc
        if owner is None:
            raise UnknownFillError(f"fill {bf.broker_fill_id}: broker order missing — quarantine")
        if (owner.broker_order_id != bf.broker_order_id or owner.symbol != bf.symbol
                or owner.side != bf.side):
            raise BrokerFillInvalid(f"fill {bf.broker_fill_id}: broker ownership identity mismatch")
        order_id = resolve_local_order_id(None, owner.broker_order_id, owner.client_order_id, conn)
        if order_id is None:
            cid = owner.client_order_id or ""
            # Include all registered engine accounts, not just this account's namespace.
            namespaces = {account_id} | {r[0] for r in conn.execute("SELECT account_id FROM trading_accounts")}
            if cid.startswith("AGENTIC_") or any(cid.startswith(a + ":") for a in namespaces):
                raise UnknownFillError(f"fill {bf.broker_fill_id}: engine ownership without local lineage — quarantine")
    side = bf.side
    qty = float(bf.qty)
    price = float(bf.price)
    fee = float(bf.fee)
    filled_at = bf.filled_at

    if order_id is None:
        # 0568: BROKER_EXTERNAL — fill from broker with no matching local order.
        # Ingest economically (update position/cash) but do NOT invent order/intent lineage.
        if not bf.broker_fill_id:
            raise BrokerFillInvalid("external fill: broker_fill_id is empty — rejecting")
        if not (qty > 0 and math.isfinite(qty)):
            raise BrokerFillInvalid(f"external fill {bf.broker_fill_id}: qty={qty} must be positive and finite")
        if not (price > 0 and math.isfinite(price)):
            raise BrokerFillInvalid(f"external fill {bf.broker_fill_id}: price={price} must be positive and finite")
        if not (fee >= 0 and math.isfinite(fee)):
            raise BrokerFillInvalid(f"external fill {bf.broker_fill_id}: fee={fee} must be non-negative and finite")
        if bf.account_id != account_id:
            raise BrokerFillInvalid(
                f"external fill {bf.broker_fill_id}: account_id mismatch: "
                f"fill={bf.account_id!r} expected={account_id!r}"
            )
        _log.warning(
            "apply_broker_fill: BROKER_EXTERNAL fill %r for %s — no local order; ingesting economically",
            bf.broker_fill_id, account_id,
        )
        _ext_now = datetime.now(timezone.utc).isoformat()
        _ext_sell = side in ("SELL", "SELL_TO_OPEN")
        try:
            # 0570: read position BEFORE INSERT so realized PnL is computed and stored atomically
            _ext_pos = conn.execute(
                "SELECT qty, avg_cost FROM position_snapshots WHERE account_id=? AND symbol=?",
                (account_id, bf.symbol),
            ).fetchone()
            from .fill_economics import calculate_fill_economics
            economics = calculate_fill_economics(side, qty, price, fee,
                _ext_pos["qty"] or 0 if _ext_pos else 0,
                _ext_pos["avg_cost"] or 0 if _ext_pos else 0)
            _ext_cur = conn.execute(
                """INSERT OR IGNORE INTO fills
                   (fill_id, order_id, account_id, symbol, side, qty, price,
                    fee, fill_source, filled_at, origin, engine_managed,
                    first_seen_at, reconciled_at, cost_basis, realized_pnl, realized_pnl_pct)
                   VALUES (?,NULL,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (bf.broker_fill_id, account_id, bf.symbol,
                 side, qty, price, fee, "broker_external", filled_at,
                 "BROKER_EXTERNAL", 0, _ext_now, _ext_now,
                 economics.cost_basis, economics.realized_pnl, economics.realized_pnl_pct),
            )
            if _ext_cur.rowcount == 0:
                # 0571: reconciled_at advances on every successful broker observation
                conn.execute(
                    "UPDATE fills SET reconciled_at=? WHERE fill_id=?",
                    (_ext_now, bf.broker_fill_id),
                )
                conn.commit()
                return FillResult.ALREADY_APPLIED
            if _ext_sell:
                _ext_old_qty = float(_ext_pos["qty"] or 0) if _ext_pos else 0.0
                if qty > _ext_old_qty + 1e-6:
                    raise ImpossibleSellError(
                        f"external fill {bf.broker_fill_id}: sell qty {qty} exceeds held qty {_ext_old_qty}"
                    )
                _ext_new_qty = float(economics.new_qty)
                if _ext_new_qty <= 1e-9:
                    conn.execute(
                        "DELETE FROM position_snapshots WHERE account_id=? AND symbol=?",
                        (account_id, bf.symbol),
                    )
                elif _ext_pos:
                    conn.execute(
                        "UPDATE position_snapshots SET qty=? WHERE account_id=? AND symbol=?",
                        (_ext_new_qty, account_id, bf.symbol),
                    )
            else:
                if _ext_pos:
                    _ext_new_qty2 = economics.new_qty
                    _ext_new_avg2 = economics.new_avg_cost
                    conn.execute(
                        "UPDATE position_snapshots SET qty=?, avg_cost=? WHERE account_id=? AND symbol=?",
                        (_ext_new_qty2, _ext_new_avg2, account_id, bf.symbol),
                    )
                else:
                    conn.execute(
                        """INSERT INTO position_snapshots
                           (account_id, symbol, qty, avg_cost, instrument_type, as_of)
                           VALUES (?,?,?,?,?,?)""",
                        (account_id, bf.symbol, qty, price, "EQUITY",
                         filled_at[:10] if filled_at else None),
                    )
            _ext_cash_delta = economics.cash_delta
            conn.execute(
                "UPDATE trading_accounts SET current_cash = current_cash + ? WHERE account_id=?",
                (_ext_cash_delta, account_id),
            )
            conn.commit()
            return FillResult.APPLIED_EXTERNAL
        except BrokerStateIntegrityError:
            conn.rollback()
            raise
        except Exception:
            conn.rollback()
            raise

    # ── 0286: validate fill identity and economics before any DB write ─────────
    if not bf.broker_fill_id:
        raise BrokerFillInvalid(
            f"fill for order {order_id}: broker_fill_id is empty — rejecting"
        )
    if not (qty > 0 and math.isfinite(qty)):
        raise BrokerFillInvalid(
            f"fill {bf.broker_fill_id}: qty={qty} must be positive and finite"
        )
    if not (price > 0 and math.isfinite(price)):
        raise BrokerFillInvalid(
            f"fill {bf.broker_fill_id}: price={price} must be positive and finite"
        )
    if not (fee >= 0 and math.isfinite(fee)):
        raise BrokerFillInvalid(
            f"fill {bf.broker_fill_id}: fee={fee} must be non-negative and finite"
        )
    if bf.account_id != account_id:
        raise BrokerFillInvalid(
            f"fill {bf.broker_fill_id}: account_id mismatch: "
            f"fill={bf.account_id!r} expected={account_id!r}"
        )

    # Fetch order row for field validation; reused for mutation calculations inside try (0286)
    _order_row = conn.execute(
        "SELECT account_id, symbol, side, broker_order_id, quantity, fill_qty, fill_cash "
        "FROM orders WHERE order_id=?",
        (order_id,),
    ).fetchone()
    if _order_row is None:
        raise UnknownFillError(
            f"fill {bf.broker_fill_id}: order {order_id!r} not found — quarantine"
        )
    if _order_row["account_id"] != account_id:
        raise BrokerFillInvalid(f"fill {bf.broker_fill_id}: local order account mismatch")
    if bf.symbol != _order_row["symbol"]:
        raise BrokerFillInvalid(
            f"fill {bf.broker_fill_id}: symbol mismatch: "
            f"fill={bf.symbol!r} order={_order_row['symbol']!r}"
        )
    if side != _order_row["side"]:
        raise BrokerFillInvalid(
            f"fill {bf.broker_fill_id}: side mismatch: "
            f"fill={side!r} order={_order_row['side']!r}"
        )
    # Only validate broker_order_id when the order has a real broker-assigned ID; skip when
    # the order is broker_order_id=NULL (client_order_id crash-recovery path via tier-3 resolver)
    _order_broker_oid = _order_row["broker_order_id"]
    if _order_broker_oid and bf.broker_order_id != _order_broker_oid:
        raise BrokerFillInvalid(
            f"fill {bf.broker_fill_id}: broker_order_id mismatch: "
            f"fill={bf.broker_order_id!r} order={_order_broker_oid!r}"
        )

    try:
        from .fill_economics import calculate_fill_economics
        pos_row = conn.execute(
            "SELECT qty, avg_cost FROM position_snapshots WHERE account_id=? AND symbol=?",
            (account_id, bf.symbol),
        ).fetchone()
        economics = calculate_fill_economics(side, qty, price, fee,
            pos_row["qty"] or 0 if pos_row else 0,
            pos_row["avg_cost"] or 0 if pos_row else 0)
        # Atomic dedup: INSERT OR IGNORE lets the unique PK enforce idempotency (0261)
        _eng_now = datetime.now(timezone.utc).isoformat()
        cursor = conn.execute(
            """INSERT OR IGNORE INTO fills
               (fill_id, order_id, account_id, symbol, side, qty, price,
                fee, fill_source, filled_at, origin, engine_managed,
                first_seen_at, reconciled_at, cost_basis, realized_pnl, realized_pnl_pct)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (bf.broker_fill_id, order_id, account_id, bf.symbol,
             side, qty, price, fee, "broker_import", filled_at,
             "ENGINE", 1, _eng_now, _eng_now,
             economics.cost_basis, economics.realized_pnl, economics.realized_pnl_pct),
        )
        if cursor.rowcount == 0:
            # Fill committed by an earlier call (or by ShadowBroker.attempt_fill() in shadow
            # mode). Write audit row if missing so the record is always present regardless of
            # which code path first inserted the fill (0293).
            _ea_missing = not conn.execute(
                "SELECT 1 FROM executed_actions WHERE fill_id=?", (bf.broker_fill_id,)
            ).fetchone()
            if _ea_missing:
                _ir = conn.execute(
                    """SELECT ti.recommendation_id
                       FROM trade_intents ti
                       JOIN orders o ON ti.intent_id = o.intent_id
                       WHERE o.order_id = ?""",
                    (order_id,),
                ).fetchone()
                _fill_src_row = conn.execute(
                    "SELECT fill_source, filled_at FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
                ).fetchone()
                _fill_src = _fill_src_row["fill_source"] if _fill_src_row else "broker_import"
                _fill_at = _fill_src_row["filled_at"] if _fill_src_row else filled_at
                conn.execute(
                    """INSERT OR IGNORE INTO executed_actions
                       (recommendation_id, ticker, action, quantity, execution_price,
                        execution_date, fees, notes, source, created_at, fill_id)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        _ir["recommendation_id"] if _ir else None,
                        bf.symbol,
                        side,
                        qty,
                        price,
                        _fill_at[:10] if _fill_at else None,
                        fee,
                        f"fill_source={_fill_src}",
                        _fill_src,
                        time.time(),
                        bf.broker_fill_id,
                    ),
                )
            # 0571: reconciled_at advances on every successful broker observation
            conn.execute(
                "UPDATE fills SET reconciled_at=? WHERE fill_id=?",
                (_now_utc().isoformat(), bf.broker_fill_id),
            )
            conn.commit()
            return FillResult.ALREADY_APPLIED  # fill already applied; mutations skipped

        # Only the transaction that wrote the fill row proceeds with mutations
        total_qty = float(_order_row["quantity"] or 0)
        prior_fill_qty = float(_order_row["fill_qty"] or 0)
        remaining = max(0.0, total_qty - prior_fill_qty)
        # Overfill guard: allow tiny float tolerance (0262)
        if qty > remaining + 1e-6:
            raise OverfillError(
                f"fill {bf.broker_fill_id}: fill qty {qty} exceeds remaining {remaining:.6f} for order {order_id}"
            )

        new_fill_qty = prior_fill_qty + qty
        new_fill_cash = float(_order_row["fill_cash"] or 0) + qty * price
        new_state = "FILLED" if new_fill_qty >= total_qty - 1e-9 else "PARTIALLY_FILLED"
        conn.execute(
            "UPDATE orders SET fill_qty=?, fill_cash=?, state=?, broker_order_id=COALESCE(broker_order_id, ?) WHERE order_id=?",
            (new_fill_qty, new_fill_cash, new_state, bf.broker_order_id, order_id),
        )

        # Update position: BUY increases qty/avg_cost; SELL decreases qty
        is_sell = side in ("SELL", "SELL_TO_OPEN")
        if is_sell:
            old_qty = float(pos_row["qty"] or 0) if pos_row else 0.0
            # Impossible sell guard: refuse silently clamping to zero (0262)
            if qty > old_qty + 1e-6:
                raise ImpossibleSellError(
                    f"fill {bf.broker_fill_id}: sell qty {qty} exceeds held qty {old_qty} for {bf.symbol}"
                )
            new_qty = float(economics.new_qty)
            if new_qty <= 1e-9:
                conn.execute(
                    "DELETE FROM position_snapshots WHERE account_id=? AND symbol=?",
                    (account_id, bf.symbol),
                )
            elif pos_row:
                conn.execute(
                    "UPDATE position_snapshots SET qty=? WHERE account_id=? AND symbol=?",
                    (new_qty, account_id, bf.symbol),
                )
        else:
            if pos_row:
                new_qty = economics.new_qty
                new_avg = economics.new_avg_cost
                conn.execute(
                    "UPDATE position_snapshots SET qty=?, avg_cost=? WHERE account_id=? AND symbol=?",
                    (new_qty, new_avg, account_id, bf.symbol),
                )
            else:
                conn.execute(
                    """INSERT INTO position_snapshots
                       (account_id, symbol, qty, avg_cost, instrument_type, as_of)
                       VALUES (?,?,?,?,?,?)""",
                    (account_id, bf.symbol, qty, price, "EQUITY", filled_at[:10]),
                )

        # Update cash: BUY decreases, SELL increases
        cash_delta = economics.cash_delta
        conn.execute(
            "UPDATE trading_accounts SET current_cash = current_cash + ? WHERE account_id=?",
            (cash_delta, account_id),
        )

        # Update intent status if order is now fully filled
        if new_fill_qty >= total_qty - 1e-9:
            conn.execute(
                """UPDATE trade_intents SET status='FILLED'
                   WHERE intent_id = (SELECT intent_id FROM orders WHERE order_id=?)""",
                (order_id,),
            )

        # Write audit record atomically with the fill (0293).
        # INSERT OR IGNORE ensures idempotency on replay without raising.
        _intent_row = conn.execute(
            """SELECT ti.recommendation_id
               FROM trade_intents ti
               JOIN orders o ON ti.intent_id = o.intent_id
               WHERE o.order_id = ?""",
            (order_id,),
        ).fetchone()
        _rec_id = _intent_row["recommendation_id"] if _intent_row else None
        conn.execute(
            """INSERT OR IGNORE INTO executed_actions
               (recommendation_id, ticker, action, quantity, execution_price,
                execution_date, fees, notes, source, created_at, fill_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _rec_id,
                bf.symbol,
                side,
                qty,
                price,
                filled_at[:10] if filled_at else None,
                fee,
                "fill_source=broker_import",
                "broker_import",
                time.time(),
                bf.broker_fill_id,
            ),
        )

        # 0333: spawn trade outcome row for fill-price-entry learning signal
        _spawn_trade_outcome(conn, bf.broker_fill_id, order_id, bf.symbol,
                             price, qty, fee, filled_at)
        conn.commit()
        return FillResult.APPLIED

    except BrokerStateIntegrityError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise


def apply_broker_order_event(
    event,  # BrokerOrderEvent
    account_id: str,
    conn: sqlite3.Connection,
) -> None:
    """Central state reducer for non-fill broker order events (0261).

    Valid transitions:
      WORKING            → CANCELLED       (CANCELLED event)
      WORKING            → EXPIRED         (EXPIRED event)
      CANCEL_REQUESTED   → CANCELLED       (CANCELLED event)
      PARTIALLY_FILLED   → CANCELLED       (CANCELLED event — partial fill accepted, rest cancelled)

    Invalid/impossible transitions (e.g. CANCELLED on a FILLED order) log a warning
    and return without mutation. Fill events are not handled here — route them to
    apply_broker_fill() instead.
    """
    order_id = resolve_local_order_id(
        event.local_order_id, event.broker_order_id,
        getattr(event, "client_order_id", None), conn
    )
    event_type = event.event_type

    if event_type in ("FILLED", "PARTIALLY_FILLED"):
        _log.warning(
            "apply_broker_order_event: fill event %s for order %s — route to apply_broker_fill()",
            event_type, order_id,
        )
        return

    row = conn.execute(
        "SELECT state FROM orders WHERE order_id=?", (order_id,)
    ).fetchone()
    if row is None:
        _log.warning(
            "apply_broker_order_event: order %s not found in local DB (event: %s)", order_id, event_type
        )
        return

    current_state = row["state"]

    VALID_CANCEL = {"WORKING", "CANCEL_REQUESTED", "PARTIALLY_FILLED"}
    VALID_EXPIRE = {"WORKING", "PARTIALLY_FILLED"}

    if event_type == "CANCELLED":
        if current_state not in VALID_CANCEL:
            _log.warning(
                "apply_broker_order_event: ignoring CANCELLED for order %s in state %s",
                order_id, current_state,
            )
            return
        conn.execute("UPDATE orders SET state='CANCELLED' WHERE order_id=?", (order_id,))
        conn.execute(
            """UPDATE trade_intents SET status='CANCELLED'
               WHERE intent_id = (SELECT intent_id FROM orders WHERE order_id=?)""",
            (order_id,),
        )
        conn.commit()

    elif event_type == "EXPIRED":
        if current_state not in VALID_EXPIRE:
            _log.warning(
                "apply_broker_order_event: ignoring EXPIRED for order %s in state %s",
                order_id, current_state,
            )
            return
        conn.execute("UPDATE orders SET state='EXPIRED' WHERE order_id=?", (order_id,))
        conn.execute(
            """UPDATE trade_intents SET status='EXPIRED'
               WHERE intent_id = (SELECT intent_id FROM orders WHERE order_id=?)""",
            (order_id,),
        )
        conn.commit()

    elif event_type == "REJECTED":
        # Broker rejected the order after submission (e.g. margin violation, bad params) (0290).
        VALID_REJECT = {"WORKING", "PENDING_SUBMIT", "PARTIALLY_FILLED"}
        if current_state not in VALID_REJECT:
            _log.warning(
                "apply_broker_order_event: ignoring REJECTED for order %s in state %s",
                order_id, current_state,
            )
            return
        conn.execute("UPDATE orders SET state='REJECTED' WHERE order_id=?", (order_id,))
        conn.execute(
            """UPDATE trade_intents SET status='REJECTED'
               WHERE intent_id = (SELECT intent_id FROM orders WHERE order_id=?)""",
            (order_id,),
        )
        conn.commit()

    else:
        raise BrokerStateIntegrityError(
            f"apply_broker_order_event: unrecognized event_type {event_type!r} for order {order_id} "
            f"— adapter contract violation (0290)"
        )


def initialize_trading_session(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
    *,
    _fill_stats: Optional[dict] = None,
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

    # Step 0: account-ID binding check (0272, 0276)
    # Policy load failure always halts — a missing/corrupt policy cannot safely disable the check.
    try:
        _init_policy = load_policy(account_id)
        expected_bid = _init_policy.expected_broker_account_id()
        _require_binding = _init_policy.require_account_binding()
    except Exception as exc:
        _log.error(
            "initialize_trading_session: policy load failed for %s: %s — HALTED",
            account_id, exc,
        )
        return TradingReadyState.HALTED
    if _require_binding and expected_bid is None:
        _log.error(
            "initialize_trading_session: require_account_binding=True but no "
            "expected_broker_account_id configured for %s — HALTED",
            account_id,
        )
        return TradingReadyState.HALTED
    if expected_bid:
        try:
            actual_bid = broker.get_account_id()
        except Exception as exc:
            _log.error(
                "initialize_trading_session: cannot verify broker account ID for %s: %s — HALTED",
                account_id, exc,
            )
            return TradingReadyState.HALTED
        if actual_bid != expected_bid:
            _log.error(
                "initialize_trading_session: ACCOUNT_MISMATCH for %s — expected %r, got %r — HALTED",
                account_id, expected_bid, actual_bid,
            )
            return TradingReadyState.HALTED

    # Step 1: verify broker connectivity
    try:
        broker.get_broker_account(account_id)
    except Exception as exc:
        _log.error("initialize_trading_session: broker unreachable for %s: %s", account_id, exc)
        return TradingReadyState.HALTED

    # 0569: resolve broker_order_id on PENDING_SUBMIT orders before fill import so the
    # fill resolver can match by broker_order_id during the crash-recovery window.
    # Lookup failures halt before any ambiguous fill can be imported (0572).
    _pending_submit_rows = conn.execute(
        "SELECT order_id, client_order_id FROM orders WHERE account_id=? AND state='PENDING_SUBMIT'",
        (account_id,),
    ).fetchall()
    for _ps in _pending_submit_rows:
        _ps_cid = _ps["client_order_id"]
        if not _ps_cid:
            continue
        try:
            _ps_bo = broker.find_order_by_client_order_id(_ps_cid)
            if _ps_bo is not None and getattr(_ps_bo, "broker_order_id", None):
                conn.execute(
                    "UPDATE orders SET broker_order_id=?, updated_at=?"
                    " WHERE order_id=? AND broker_order_id IS NULL",
                    (_ps_bo.broker_order_id, _now_utc().isoformat(), _ps["order_id"]),
                )
                conn.commit()
        except Exception as _ps_exc:
            _log.warning(
                "initialize_trading_session: PENDING_SUBMIT pre-resolution for %s failed: %s — HALTED",
                _ps["order_id"], _ps_exc,
            )
            return TradingReadyState.HALTED

    # Step 2-3: import fills since last sync atomically; halt on any failure (0245, 0257)
    try:
        last_sync_row = conn.execute(
            "SELECT last_fill_synced_at FROM trading_accounts WHERE account_id=?", (account_id,)
        ).fetchone()
        last_sync = last_sync_row["last_fill_synced_at"] if last_sync_row else None

        # Query from last_cursor - FILL_REPLAY_WINDOW to catch late-arriving fills (0257)
        since_for_query: Optional[str] = None
        if last_sync:
            cursor_ts = _parse_iso(last_sync) - timedelta(minutes=_FILL_REPLAY_WINDOW_MINUTES)
            since_for_query = cursor_ts.isoformat()
        # Fresh account: since_for_query=None → fetch all fills (never initialise to now)

        broker_fills = broker.get_fills(account_id, since=since_for_query)
        imported = 0
        max_filled_at: Optional[str] = None
        _init_seen_ids: set[str] = set()
        _init_new_ids: set[str] = set()
        if _fill_stats is not None:
            _fill_stats.update(seen_ids=_init_seen_ids, new_ids=_init_new_ids)
        for bf in broker_fills:
            if bf.broker_fill_id:
                _init_seen_ids.add(bf.broker_fill_id)
            result = apply_broker_fill(bf, account_id, conn, broker=broker)  # idempotent; skips duplicates (0252)
            if result in (FillResult.APPLIED, FillResult.APPLIED_EXTERNAL):
                imported += 1
                if bf.broker_fill_id:
                    _init_new_ids.add(bf.broker_fill_id)
            # 0567: advance cursor for all observed fills (APPLIED, APPLIED_EXTERNAL, ALREADY_APPLIED)
            if bf.filled_at and (max_filled_at is None or bf.filled_at > max_filled_at):
                max_filled_at = bf.filled_at
        if imported > 0:
            _log.info("initialize_trading_session: imported %d broker fills for %s", imported, account_id)
        # Advance cursor to max filled_at across all observed fills (0567)
        sync_mark = max_filled_at or last_sync
        if sync_mark:
            conn.execute(
                "UPDATE trading_accounts SET last_fill_synced_at=? WHERE account_id=?",
                (sync_mark, account_id),
            )
            conn.commit()
    except Exception as exc:
        _log.error("initialize_trading_session: fill import failed for %s: %s — HALTED", account_id, exc)
        return TradingReadyState.HALTED  # (0245) fill-import failure → halt, not silent skip

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
