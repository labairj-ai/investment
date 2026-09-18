"""IntentBuilder: converts an ACCEPTED recommendation into a TradeIntent (0195).

This is the only place recommendations flow into the execution path.
"""
from __future__ import annotations

import json
import math
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

import agent_db
from .models import (
    InstrumentType,
    IntentStatus,
    OrderType,
    Side,
    TimeInForce,
    TradeIntent,
)
from .policy import TradingPolicy
from . import market_calendar
from . import market_data as _market_data

_SUPPORTED_ACTIONS = {"BUY", "TRIM", "EXIT"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _get_account_state(
    account_id: str, symbol: str, conn: sqlite3.Connection
) -> tuple[float, float, float]:
    """Return (current_cash, position_qty, nav_approx using market value when available)."""
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
        "SELECT qty, avg_cost, market_value FROM position_snapshots WHERE account_id=?",
        (account_id,),
    ).fetchall()
    pos_value = 0.0
    for r in all_pos:
        mv = r["market_value"] if "market_value" in r.keys() else None
        if mv is not None:
            pos_value += float(mv)
        else:
            pos_value += float(r["qty"] or 0) * float(r["avg_cost"] or 0)
    nav = cash + pos_value

    return cash, pos_qty, nav


def _get_strategy_config_hash() -> Optional[str]:
    """Return the strategy.json hash if available."""
    try:
        from pathlib import Path
        import hashlib
        path = Path(__file__).resolve().parent.parent / "config" / "strategy.json"
        raw = path.read_bytes()
        return hashlib.sha256(raw).hexdigest()[:12]
    except Exception:
        return None


def _fetch_quote_fields(ticker: str, fallback_price: float) -> dict:
    """Fetch live bid/ask for a ticker; fall back to payload price (0356).

    Returns dict with decision_last, decision_mid, decision_bid, decision_ask,
    decision_spread_bps, quote_timestamp, price_source, and updated decision_market_price.
    """
    try:
        quote = _market_data._get_quote(ticker)
        if quote and quote.bid > 0 and quote.ask > 0:
            mid = (quote.bid + quote.ask) / 2.0
            spread_bps = (quote.ask - quote.bid) / mid * 10000 if mid > 0 else None
            return {
                "decision_bid": quote.bid,
                "decision_ask": quote.ask,
                "decision_last": mid,
                "decision_mid": mid,
                "decision_spread_bps": round(spread_bps, 2) if spread_bps is not None else None,
                "quote_timestamp": quote.timestamp,
                "price_source": "yfinance",
                "decision_market_price": mid,
            }
    except Exception:
        pass
    return {
        "decision_bid": None,
        "decision_ask": None,
        "decision_last": fallback_price,
        "decision_mid": None,
        "decision_spread_bps": None,
        "quote_timestamp": None,
        "price_source": "payload",
        "decision_market_price": fallback_price,
    }


def build_intent_from_variant(
    variant_id: int,
    account_id: str,
    policy: TradingPolicy,
    conn: sqlite3.Connection,
) -> Optional[TradeIntent]:
    """Build a TradeIntent from a decision_variants row for a PAPER_CHALLENGER account (0337).

    Uses the variant's ticker, action, and price — never the champion recommendation's ticker.
    Idempotent: returns existing PENDING/WORKING intent for this account+variant.
    """
    var = conn.execute(
        "SELECT * FROM decision_variants WHERE id=?", (variant_id,)
    ).fetchone()
    if not var:
        return None

    ticker = var["variant_ticker"]
    action = var["action"] or "BUY"
    episode_id = var["episode_id"]

    if not ticker or action not in _SUPPORTED_ACTIONS:
        return None

    # 0352: all-status query — any terminal intent permanently closes this variant decision
    _TERMINAL = {"CANCELLED", "REJECTED", "EXPIRED", "FILLED"}
    existing = conn.execute(
        "SELECT * FROM trade_intents WHERE decision_variant_id=? LIMIT 1",
        (variant_id,),
    ).fetchone()
    if existing:
        if existing["status"] in _TERMINAL:
            return None  # variant permanently closed; do not re-enter
        return TradeIntent.from_db_row(existing)

    raw_price = float(var["price"] or 0)
    if raw_price <= 0:
        return None

    cash, pos_qty, nav = _get_account_state(account_id, ticker, conn)

    if action == "BUY":
        side = Side.BUY
        limit_price = round(raw_price * (1 + policy.max_slippage_pct() / 100), 2)
        if var["quantity"] and float(var["quantity"]) >= 1:
            quantity = int(float(var["quantity"]))
        elif var["target_weight_pct"] and float(var["target_weight_pct"]) > 0:
            target_dollars = nav * float(var["target_weight_pct"]) / 100.0
            quantity = math.floor(target_dollars / limit_price)
        else:
            target_weight = min(policy.max_new_position_pct(), policy.max_single_position_pct())
            quantity = math.floor(nav * target_weight / 100.0 / limit_price)
        if quantity < 1:
            return None

    elif action == "TRIM":
        if pos_qty <= 0:
            return None
        side = Side.SELL
        limit_price = round(raw_price * (1 - policy.max_slippage_pct() / 100), 2)
        quantity = math.floor(pos_qty * 0.25)
        if quantity < 1:
            return None

    elif action == "EXIT":
        if pos_qty <= 0:
            return None
        side = Side.SELL
        limit_price = round(raw_price * (1 - policy.max_slippage_pct() / 100), 2)
        quantity = pos_qty

    else:
        return None

    thesis_version = var["thesis_version"] if var["thesis_version"] else None
    if thesis_version is None:
        tv_row = conn.execute(
            "SELECT id FROM investment_theses WHERE ticker=? ORDER BY id DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if tv_row:
            thesis_version = tv_row["id"]

    now = _now_utc().isoformat()
    valid_until = market_calendar.next_market_close().isoformat()

    # 0356: fetch live quote; fall back to payload price when unavailable
    qf = _fetch_quote_fields(ticker, raw_price)

    intent = TradeIntent(
        intent_id=str(uuid.uuid4()),
        account_id=account_id,
        recommendation_id=None,
        agent_run_id=None,
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
        strategy="agentic_equity_v1",
        thesis_version=thesis_version,
        strategy_config_hash=_get_strategy_config_hash(),
        policy_hash=policy.policy_hash(),
        valid_until=valid_until,
        created_at=now,
        status=IntentStatus.PENDING,
        episode_id=episode_id,
        decision_origin="PAPER_CHALLENGER",
        code_commit_sha=agent_db.CODE_COMMIT_SHA,
        decision_variant_id=variant_id,
        decision_market_price=qf["decision_market_price"],
        decision_bid=qf["decision_bid"],
        decision_ask=qf["decision_ask"],
        decision_last=qf["decision_last"],
        decision_mid=qf["decision_mid"],
        decision_spread_bps=qf["decision_spread_bps"],
        quote_timestamp=qf["quote_timestamp"],
        price_source=qf["price_source"],
    )

    d = intent.to_db_dict()
    cols = ", ".join(d.keys())
    placeholders = ", ".join(f":{k}" for k in d.keys())
    conn.execute(f"INSERT INTO trade_intents ({cols}) VALUES ({placeholders})", d)
    conn.commit()
    return intent


def build_intent(
    recommendation_id: int,
    account_id: str,
    policy: TradingPolicy,
    conn: sqlite3.Connection,
) -> Optional[TradeIntent]:
    """Build a TradeIntent for an ACCEPTED recommendation.

    Returns existing intent if already built (idempotent).
    Returns None if recommendation is not executable for this account.

    0337: For ALPACA accounts, if a PAPER_CHALLENGER variant exists for the episode,
    delegates to build_intent_from_variant() so the variant's ticker (not the champion's)
    is what actually executes. This is the clean champion/challenger separation.

    Sizing (0207): reads target_weight_pct or quantity from action_payload_json when present.
    Falls back to max_new_position_pct when neither is set (backward-compatible).
    """
    # Idempotency: return existing intent (any non-terminal status) for this rec/account.
    # The UNIQUE index on (account_id, recommendation_id) enforces this at the DB layer (0314),
    # but we check here first to return the existing intent rather than silently ignoring.
    existing = conn.execute(
        """SELECT * FROM trade_intents
           WHERE recommendation_id=? AND account_id=?
             AND status NOT IN ('CANCELLED','REJECTED','EXPIRED')
           ORDER BY created_at DESC LIMIT 1""",
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

    # 0331: propagate episode_id from the source recommendation
    rec_keys = rec.keys() if hasattr(rec, "keys") else []
    episode_id = rec["episode_id"] if "episode_id" in rec_keys else None

    # 0353: route solely by trading_accounts.role; no string-match fallback.
    # An account with role=NULL or role != 'paper_challenger' gets champion behavior.
    acct_row = conn.execute(
        "SELECT role FROM trading_accounts WHERE account_id=?", (account_id,)
    ).fetchone()
    acct_role = acct_row["role"] if acct_row and acct_row["role"] else None
    if acct_role is None:
        import logging as _logging
        _logging.getLogger(__name__).debug(
            "[intent_builder] account %s has NULL role — defaulting to champion behavior", account_id
        )
    is_paper_challenger = (acct_role == "paper_challenger")
    if episode_id and is_paper_challenger:
        variant_row = conn.execute(
            """SELECT id FROM decision_variants
               WHERE episode_id=? AND origin='PAPER_CHALLENGER' LIMIT 1""",
            (episode_id,),
        ).fetchone()
        if variant_row:
            return build_intent_from_variant(variant_row["id"], account_id, policy, conn)

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
        return None

    # 0356: fetch live quote; fall back to payload price when unavailable
    qf = _fetch_quote_fields(ticker, limit_price)
    decision_market_price = qf["decision_market_price"]

    if action == "BUY":
        side = Side.BUY
        buy_lim = limit_price * (1 + policy.max_slippage_pct() / 100)
        limit_price = round(buy_lim, 2)

        # 0207: agent-proposed sizing; fallback to policy max only when absent
        if payload.get("quantity") and int(payload["quantity"]) >= 1:
            quantity = int(payload["quantity"])
        elif payload.get("target_weight_pct") and float(payload["target_weight_pct"]) > 0:
            target_dollars = nav * float(payload["target_weight_pct"]) / 100.0
            quantity = math.floor(target_dollars / limit_price)
        else:
            target_weight = min(
                policy.max_new_position_pct(),
                policy.max_single_position_pct(),
            )
            target_dollars = nav * target_weight / 100.0
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
    # Use market_calendar for valid_until so weekends/holidays are skipped (0203)
    valid_until = market_calendar.next_market_close().isoformat()

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
        strategy="agentic_equity_v1",
        thesis_version=thesis_version,
        strategy_config_hash=_get_strategy_config_hash(),
        policy_hash=policy.policy_hash(),  # 0204
        valid_until=valid_until,
        created_at=now,
        status=IntentStatus.PENDING,
        episode_id=episode_id,
        decision_origin="CHAMPION",
        code_commit_sha=agent_db.CODE_COMMIT_SHA,
        decision_market_price=decision_market_price,
        decision_bid=qf["decision_bid"],
        decision_ask=qf["decision_ask"],
        decision_last=qf["decision_last"],
        decision_mid=qf["decision_mid"],
        decision_spread_bps=qf["decision_spread_bps"],
        quote_timestamp=qf["quote_timestamp"],
        price_source=qf["price_source"],
    )

    d = intent.to_db_dict()
    cols = ", ".join(d.keys())
    placeholders = ", ".join(f":{k}" for k in d.keys())
    # INSERT OR IGNORE: the UNIQUE index on (account_id, recommendation_id) prevents
    # duplicates even under concurrent or retry conditions (0314).
    cur = conn.execute(
        f"INSERT OR IGNORE INTO trade_intents ({cols}) VALUES ({placeholders})", d
    )
    conn.commit()

    if cur.rowcount == 0:
        # Another process raced us; return the row that won.
        row = conn.execute(
            "SELECT * FROM trade_intents WHERE recommendation_id=? AND account_id=? LIMIT 1",
            (recommendation_id, account_id),
        ).fetchone()
        return TradeIntent.from_db_row(row) if row else None

    return intent
