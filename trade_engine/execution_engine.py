"""ExecutionEngine: orchestrates Intent → Risk → Shadow → Fill → executed_actions (0196)."""
from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from .models import (
    ExecutionResult,
    Fill,
    IntentStatus,
    OrderState,
    TradeIntent,
    TradingAccount,
)
from .policy import TradingPolicy, load_policy
from .risk_engine import evaluate as risk_evaluate
from .shadow_broker import Quote, ShadowBroker


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_quote(symbol: str) -> Optional[Quote]:
    """Fetch live bid/ask from yfinance. Returns None on failure."""
    try:
        import yfinance as yf
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
            return Quote(bid=bid, ask=ask, timestamp=_now_utc().isoformat())
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


def process_intent(intent_id: str, conn: sqlite3.Connection) -> ExecutionResult:
    """Run the full execution pipeline for a single intent.

    Crash safety:
    - If the order already exists (SUBMITTED/WORKING), skip re-submission
      and re-attempt fill only.
    - If a fill already exists for the order, executed_actions write is
      idempotent via fill_id unique index.
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

    # ── Order submission (idempotent) ─────────────────────────────────────────
    broker = ShadowBroker(conn)
    order = broker.submit_order(intent)

    # ── Fill attempt ──────────────────────────────────────────────────────────
    # Check for existing fill first (crash recovery)
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
            # No live quote available — use limit_price as both bid and ask
            fallback_quote = Quote(
                bid=intent.limit_price,
                ask=intent.limit_price,
                timestamp=_now_utc().isoformat(),
            )
            fill = broker.attempt_fill(order, fallback_quote)

    if fill:
        # Reload order to get current state
        updated_order = broker.get_order(order.order_id)
        if updated_order and updated_order.state == OrderState.FILLED:
            _update_intent_status(intent_id, IntentStatus.FILLED, conn)

        # Write to executed_actions (idempotent via fill_id unique index)
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


def run_pending_intents(account_id: str, conn: sqlite3.Connection) -> list[ExecutionResult]:
    """Process all PENDING trade intents for the given account."""
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
            # Log but don't stop processing other intents
            import logging
            logging.getLogger(__name__).error(
                "process_intent failed for %s: %s", row["intent_id"], exc
            )
    return results
