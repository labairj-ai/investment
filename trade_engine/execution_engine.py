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
from datetime import datetime, timezone
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
            f"fill_source={fill.fill_source}",
            fill.fill_source,
            time.time(),
            fill.fill_id,
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
            apply_broker_fill(bf, intent.account_id, conn)
            if fill is None:
                fill_row = conn.execute(
                    "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
                ).fetchone()
                if fill_row:
                    fill = Fill.from_db_row(fill_row)
        # Do NOT call _update_intent_status(...FILLED) — apply_broker_fill() already sets
        # intent status to FILLED when aggregate fill qty reaches order qty (0278).
        if fill:
            _write_executed_action(fill, intent, conn)
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
            apply_broker_fill(bf, intent.account_id, conn)
            if fill is None:
                fill_row = conn.execute(
                    "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
                ).fetchone()
                if fill_row:
                    fill = Fill.from_db_row(fill_row)
        if fill:
            _write_executed_action(fill, intent, conn)
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
        # Broker accepted; order is live — attach broker_order_id and poll for fills below.
        conn.execute(
            "UPDATE orders SET broker_order_id=?, state='WORKING', submitted_at=? WHERE order_id=?",
            (ack.broker_order_id, ack.accepted_at or now_str2, local_order_id),
        )
        conn.commit()
    else:
        # ERROR or unrecognized ACK state — fail closed; never silently assume WORKING (0280).
        raise BrokerSettlementIndeterminate(
            f"order {local_order_id}: unrecognized ACK normalized_state {_ack_state!r} "
            f"from broker — halting new submissions"
        )

    # ── Ingest any immediate fills via the canonical event path (0259) ────────
    # attempt_fill() is NOT called here; all fills flow through apply_broker_fill().
    fill: Optional[Fill] = None
    initial_events = broker.poll_order_events(intent.account_id, quote=bquote)
    for event in initial_events:
        # Resolve via identity resolver so broker_order_id-only events match (0263)
        event_order_id = resolve_local_order_id(
            event.local_order_id, event.broker_order_id,
            getattr(event, "client_order_id", None), conn,
        )
        if event_order_id != local_order_id:
            continue
        if event.event_type in ("FILLED", "PARTIALLY_FILLED"):
            if event.broker_fill_id:
                bf = BrokerFill(
                    broker_fill_id=event.broker_fill_id,
                    broker_order_id=event.broker_order_id,
                    symbol=intent.symbol,
                    side=intent.side.value,
                    qty=float(event.fill_qty),
                    price=float(event.fill_price),
                    filled_at=event.filled_at or _now_utc().isoformat(),
                    fee=float(event.fee),
                    local_order_id=event.local_order_id,
                    account_id=intent.account_id,
                    client_order_id=getattr(event, "client_order_id", None),
                )
                apply_broker_fill(bf, intent.account_id, conn)
                fill_row = conn.execute(
                    "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
                ).fetchone()
                if fill_row and fill is None:
                    fill = Fill.from_db_row(fill_row)
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
                    apply_broker_fill(bf, intent.account_id, conn)
                    if fill is None:
                        fill_row = conn.execute(
                            "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
                        ).fetchone()
                        if fill_row:
                            fill = Fill.from_db_row(fill_row)

    if fill:
        updated_order = broker.get_order(ack.broker_order_id)  # broker-native ID (0268)
        if updated_order and updated_order.state == OrderState.FILLED:
            _update_intent_status(intent_id, IntentStatus.FILLED, conn)
        _write_executed_action(fill, intent, conn)

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    return ExecutionResult(
        intent_id=intent_id,
        decision="APPROVED",
        order_id=local_order_id,
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
        except (BrokerSubmissionIndeterminate, BrokerStateIntegrityError):
            raise  # propagate — further intent processing must stop (0265, 0278, 0288)
        except Exception as exc:
            _log.error("process_intent failed for %s: %s", row["intent_id"], exc)
    return results


def process_open_orders(
    account_id: str,
    conn: sqlite3.Connection,
    broker: Optional[BrokerAdapter] = None,
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
                    apply_broker_fill(bf, account_id, conn)
                    fill_row = conn.execute(
                        "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
                    ).fetchone()
                    if fill_row:
                        fill = Fill.from_db_row(fill_row)
                        fills.append(fill)
                        _write_executed_action(fill, intent, conn)
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
                        apply_broker_fill(bf, account_id, conn)
                        fill_row = conn.execute(
                            "SELECT * FROM fills WHERE fill_id=?", (bf.broker_fill_id,)
                        ).fetchone()
                        if fill_row:
                            fill = Fill.from_db_row(fill_row)
                            fills.append(fill)
                            _write_executed_action(fill, intent, conn)
            elif event.event_type in ("CANCELLED", "EXPIRED"):
                apply_broker_order_event(event, account_id, conn)
            else:
                _log.warning(
                    "process_open_orders: unknown event_type %r for order %s",
                    event.event_type, local_order_id,
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
            _sync_intent_from_order(updated, row["intent_id"], conn)

    return fills, pre_fill_rejections, orders_expired


def sync_broker_state(
    account_id: str,
    conn: sqlite3.Connection,
    broker: BrokerAdapter,
) -> list[Fill]:
    """Ingest all pending broker events as the first action in a cycle (0284).

    Polls broker.poll_order_events() once and applies FILLED/PARTIALLY_FILLED events via
    apply_broker_fill() and CANCELLED/EXPIRED events via apply_broker_order_event().
    Called before process_new_intents() so fills arriving between cycles update local
    economic state before any risk evaluation occurs.

    Raises BrokerSettlementIndeterminate on unresolvable events (0285) or fill retrieval
    failures; callers treat this as HALTED. Returns the list of newly applied fills.
    """
    all_events = broker.poll_order_events(account_id)
    fills: list[Fill] = []

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
                _result = apply_broker_fill(_bf, account_id, conn)
                if _result == FillResult.APPLIED:
                    _fill_row = conn.execute(
                        "SELECT * FROM fills WHERE fill_id=?", (_bf.broker_fill_id,)
                    ).fetchone()
                    if _fill_row:
                        _fill = Fill.from_db_row(_fill_row)
                        fills.append(_fill)
                        _intent_row = conn.execute(
                            "SELECT * FROM trade_intents WHERE intent_id=?",
                            (_order_meta["intent_id"],),
                        ).fetchone()
                        if _intent_row:
                            _write_executed_action(_fill, TradeIntent.from_db_row(_intent_row), conn)
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
                    _result = apply_broker_fill(_bf, account_id, conn)
                    if _result == FillResult.APPLIED:
                        _fill_row = conn.execute(
                            "SELECT * FROM fills WHERE fill_id=?", (_bf.broker_fill_id,)
                        ).fetchone()
                        if _fill_row:
                            _fill = Fill.from_db_row(_fill_row)
                            fills.append(_fill)
                            _intent_row = conn.execute(
                                "SELECT * FROM trade_intents WHERE intent_id=?",
                                (_order_meta["intent_id"],),
                            ).fetchone()
                            if _intent_row:
                                _write_executed_action(_fill, TradeIntent.from_db_row(_intent_row), conn)

        elif _e.event_type in ("CANCELLED", "EXPIRED"):
            apply_broker_order_event(_e, account_id, conn)
        else:
            _log.warning(
                "sync_broker_state: unknown event_type %r for order_id=%r",
                _e.event_type, _local_id,
            )

    return fills


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
            "results": [],
        }

    _HALTED_BASE = {
        "execution_state": "HALTED",
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
        "results": [],
    }

    try:
        policy = load_policy(account_id)
        stale_minutes = policy.halt_on_data_stale_minutes()
    except Exception as exc:
        _log.error("POLICY_UNAVAILABLE for %s: %s — halting cycle fail-closed", account_id, exc)
        return {**_HALTED_BASE, "halt_reason": "POLICY_UNAVAILABLE"}

    if broker is None:
        broker = ShadowBrokerAdapter(conn, account_id)

    # ── 0284: Broker truth sync — ingest all pending fills before risk evaluation ─
    try:
        sync_fills = sync_broker_state(account_id, conn, broker)
    except BrokerStateIntegrityError as exc:
        _log.error(
            "BROKER_STATE_INTEGRITY in broker sync for %s: %s — halting cycle; reconcile before next run",
            account_id, exc,
        )
        return {**_HALTED_BASE, "halt_reason": "BROKER_STATE_INTEGRITY"}

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

    if not fresh:
        _log.warning(
            "Stale market marks for account %s (symbols: %s) — new intent authorization blocked",
            account_id, stale_symbols,
        )
        new_intents_blocked = True
    else:
        try:
            new_results = process_new_intents(account_id, conn, broker=broker)
        except BrokerSubmissionIndeterminate as exc:
            _log.error(
                "SUBMISSION_INDETERMINATE for %s: %s — halting cycle; reconcile before next run",
                account_id, exc,
            )
            return {**_HALTED_BASE, "halt_reason": "SUBMISSION_INDETERMINATE"}
        except BrokerStateIntegrityError as exc:
            _log.error(
                "BROKER_STATE_INTEGRITY for %s: %s — halting cycle; reconcile before next run",
                account_id, exc,
            )
            return {**_HALTED_BASE, "halt_reason": "BROKER_STATE_INTEGRITY"}

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
    except BrokerStateIntegrityError as exc:
        _log.error(
            "BROKER_STATE_INTEGRITY in fill retry for %s: %s — halting cycle; reconcile before next run",
            account_id, exc,
        )
        return {**_HALTED_BASE, "halt_reason": "BROKER_STATE_INTEGRITY"}

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
        "fills_on_sync": len(sync_fills),
        "fills_on_submission": fills_on_submission,
        "risk_rejections": risk_rejections_new + pre_fill_rejections,
        "working_orders_checked": working_orders_checked,
        "fills_on_retry": len(retry_fills),
        "total_fills": len(sync_fills) + fills_on_submission + len(retry_fills),
        "orders_expired": orders_expired_retry,
        "results": [r.to_dict() for r in new_results],
    }


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
        state = initialize_trading_session(self._account_id, self._conn, self._broker)
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
        return run_execution_cycle(
            self._account_id,
            self._conn,
            broker=self._broker,
            trading_state=TradingReadyState.TRADING_READY,
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
    # Resolve local order_id via the three-tier identity resolver (0263)
    order_id = resolve_local_order_id(
        bf.local_order_id, bf.broker_order_id, getattr(bf, "client_order_id", None), conn
    )
    side = bf.side
    qty = float(bf.qty)
    price = float(bf.price)
    fee = float(bf.fee)
    filled_at = bf.filled_at

    if order_id is None:
        raise UnknownFillError(
            f"fill {bf.broker_fill_id!r}: cannot resolve order from "
            f"local_order_id={bf.local_order_id!r}, broker_order_id={bf.broker_order_id!r} — quarantine"
        )

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
        "SELECT symbol, side, broker_order_id, quantity, fill_qty, fill_cash "
        "FROM orders WHERE order_id=?",
        (order_id,),
    ).fetchone()
    if _order_row is None:
        raise UnknownFillError(
            f"fill {bf.broker_fill_id}: order {order_id!r} not found — quarantine"
        )
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
        # Atomic dedup: INSERT OR IGNORE lets the unique PK enforce idempotency (0261)
        cursor = conn.execute(
            """INSERT OR IGNORE INTO fills
               (fill_id, order_id, account_id, symbol, side, qty, price,
                fee, fill_source, filled_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (bf.broker_fill_id, order_id, account_id, bf.symbol,
             side, qty, price, fee, "broker_import", filled_at),
        )
        if cursor.rowcount == 0:
            return FillResult.ALREADY_APPLIED  # fill already applied; no mutations needed

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
            "UPDATE orders SET fill_qty=?, fill_cash=?, state=? WHERE order_id=?",
            (new_fill_qty, new_fill_cash, new_state, order_id),
        )

        # Update position: BUY increases qty/avg_cost; SELL decreases qty
        is_sell = side in ("SELL", "SELL_TO_OPEN")
        pos_row = conn.execute(
            "SELECT qty, avg_cost FROM position_snapshots WHERE account_id=? AND symbol=?",
            (account_id, bf.symbol),
        ).fetchone()
        if is_sell:
            old_qty = float(pos_row["qty"] or 0) if pos_row else 0.0
            # Impossible sell guard: refuse silently clamping to zero (0262)
            if qty > old_qty + 1e-6:
                raise ImpossibleSellError(
                    f"fill {bf.broker_fill_id}: sell qty {qty} exceeds held qty {old_qty} for {bf.symbol}"
                )
            new_qty = old_qty - qty
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
                old_qty = float(pos_row["qty"] or 0)
                old_avg = float(pos_row["avg_cost"] or 0)
                new_qty = old_qty + qty
                new_avg = (old_qty * old_avg + qty * price) / new_qty if new_qty else price
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
        cash_delta = qty * price - fee if is_sell else -(qty * price + fee)
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

    else:
        _log.warning(
            "apply_broker_order_event: unrecognised event_type %r for order %s", event_type, order_id
        )


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

    # Step 2-3: import fills since last sync atomically; halt on any failure (0245, 0257)
    try:
        from datetime import timedelta
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
        for bf in broker_fills:
            result = apply_broker_fill(bf, account_id, conn)  # idempotent; skips duplicates (0252)
            if result == FillResult.APPLIED:
                imported += 1
                if max_filled_at is None or bf.filled_at > max_filled_at:
                    max_filled_at = bf.filled_at
        if imported > 0:
            _log.info("initialize_trading_session: imported %d broker fills for %s", imported, account_id)
        # Advance cursor to max filled_at of new fills only; never to now for fresh accounts (0257)
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
