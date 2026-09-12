"""IntentBuilder: converts an ACCEPTED recommendation into a TradeIntent (0195).

This is the only place recommendations flow into the execution path.
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from .models import (
    InstrumentType,
    IntentStatus,
    OrderType,
    Side,
    TimeInForce,
    TradeIntent,
)
from .policy import TradingPolicy

_SUPPORTED_ACTIONS = {"BUY", "TRIM", "EXIT"}
_MARKET_CLOSE = time(16, 0)  # 4:00 PM ET


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _next_market_close_utc() -> str:
    """Return ISO datetime for today's 4:00 PM ET (or tomorrow's if past close)."""
    try:
        import zoneinfo
        et_tz = zoneinfo.ZoneInfo("America/New_York")
        now_et = datetime.now(et_tz)
    except Exception:
        # Fallback: assume UTC-4
        now_et = _now_utc().replace(tzinfo=None) - timedelta(hours=4)
        et_tz = timezone(timedelta(hours=-4))

    close_et = datetime.combine(now_et.date(), _MARKET_CLOSE)
    if hasattr(et_tz, "key"):
        close_aware = close_et.replace(tzinfo=et_tz)
    else:
        close_aware = close_et.replace(tzinfo=et_tz)

    if now_et.time() >= _MARKET_CLOSE:
        # already past close — use next business day
        close_aware = close_aware + timedelta(days=1)

    return close_aware.isoformat()


def _get_account_state(
    account_id: str, symbol: str, conn: sqlite3.Connection
) -> tuple[float, float, float]:
    """Return (current_cash, position_qty, nav_approx)."""
    cash_row = conn.execute(
        "SELECT current_cash FROM trading_accounts WHERE account_id=?",
        (account_id,),
    ).fetchone()
    cash = float(cash_row["current_cash"]) if cash_row else 0.0

    pos_row = conn.execute(
        "SELECT qty FROM position_snapshots WHERE account_id=? AND symbol=?",
        (account_id, symbol),
    ).fetchone()
    pos_qty = float(pos_row["qty"]) if pos_row else 0.0

    all_pos = conn.execute(
        "SELECT qty, avg_cost FROM position_snapshots WHERE account_id=?",
        (account_id,),
    ).fetchall()
    pos_value = sum(float(r["qty"] or 0) * float(r["avg_cost"] or 0) for r in all_pos)
    nav = cash + pos_value

    return cash, pos_qty, nav


def _get_strategy_config_hash() -> Optional[str]:
    """Return the strategy.json hash if available (mirrors existing convention)."""
    try:
        from pathlib import Path
        import hashlib
        path = Path(__file__).resolve().parent.parent / "config" / "strategy.json"
        raw = path.read_bytes()
        return hashlib.sha256(raw).hexdigest()[:12]
    except Exception:
        return None


def build_intent(
    recommendation_id: int,
    account_id: str,
    policy: TradingPolicy,
    conn: sqlite3.Connection,
) -> Optional[TradeIntent]:
    """Build a TradeIntent for an ACCEPTED recommendation.

    Returns existing intent if already built (idempotent).
    Returns None if recommendation is not executable for this account.
    """
    # Idempotency: return existing PENDING intent for this rec/account
    existing = conn.execute(
        """SELECT * FROM trade_intents
           WHERE recommendation_id=? AND account_id=? AND status='PENDING'""",
        (recommendation_id, account_id),
    ).fetchone()
    if existing:
        return TradeIntent.from_db_row(existing)

    # Load recommendation
    rec = conn.execute(
        "SELECT * FROM recommendations WHERE id=?", (recommendation_id,)
    ).fetchone()
    if not rec:
        return None

    action = rec["action"]
    if action not in _SUPPORTED_ACTIONS:
        return None  # SELL_CC etc. not yet supported

    if rec["status"] != "accepted":
        return None

    ticker = rec["ticker"]
    payload = {}
    if rec["action_payload_json"]:
        try:
            payload = json.loads(rec["action_payload_json"])
        except Exception:
            pass

    cash, pos_qty, nav = _get_account_state(account_id, ticker, conn)

    # ── Sizing ────────────────────────────────────────────────────────────────
    limit_price = float(payload.get("price") or payload.get("limit_price") or 0)
    if limit_price <= 0:
        return None  # no price information

    if action == "BUY":
        target_weight = min(
            policy.max_new_position_pct(),
            policy.max_single_position_pct(),
        )
        target_dollars = nav * target_weight / 100.0
        side = Side.BUY
        # Size using slippage-adjusted limit so the risk engine cost check passes
        buy_lim = limit_price * (1 + policy.max_slippage_pct() / 100)
        limit_price = round(buy_lim, 2)
        quantity = math.floor(target_dollars / limit_price)
        if quantity < 1:
            return None

    elif action == "TRIM":
        if pos_qty <= 0:
            return None
        trim_fraction = float(payload.get("trim_fraction") or 0.25)
        quantity = math.floor(pos_qty * trim_fraction)
        if quantity < 1:
            return None
        side = Side.SELL
        sell_lim = limit_price * (1 - policy.max_slippage_pct() / 100)
        limit_price = round(sell_lim, 2)

    elif action == "EXIT":
        if pos_qty <= 0:
            return None
        quantity = pos_qty
        side = Side.SELL
        sell_lim = limit_price * (1 - policy.max_slippage_pct() / 100)
        limit_price = round(sell_lim, 2)

    else:
        return None

    thesis_version = None
    thesis_row = conn.execute(
        "SELECT id FROM investment_theses WHERE ticker=? ORDER BY id DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    if thesis_row:
        thesis_version = thesis_row["id"]

    now = _now_utc().isoformat()
    intent = TradeIntent(
        intent_id=str(uuid.uuid4()),
        account_id=account_id,
        recommendation_id=recommendation_id,
        agent_run_id=rec["run_id"],
        instrument_type=InstrumentType.EQUITY,
        symbol=ticker,
        side=side,
        quantity=float(quantity),
        contracts=None,
        option_type=None,
        strike=None,
        expiration=None,
        order_type=OrderType.LIMIT,
        limit_price=limit_price,
        time_in_force=TimeInForce.DAY,
        strategy="shadow_equity",
        thesis_version=thesis_version,
        strategy_config_hash=_get_strategy_config_hash(),
        valid_until=_next_market_close_utc(),
        created_at=now,
        status=IntentStatus.PENDING,
    )

    d = intent.to_db_dict()
    cols = ", ".join(d.keys())
    placeholders = ", ".join(f":{k}" for k in d.keys())
    conn.execute(
        f"INSERT INTO trade_intents ({cols}) VALUES ({placeholders})", d
    )
    conn.commit()

    return intent
