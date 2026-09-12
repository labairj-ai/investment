"""Independent pre-trade risk engine (0193).

Every check returns a RuleCheck. Never calls an LLM.
"""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Optional

from .models import (
    Fill,
    InstrumentType,
    IntentStatus,
    OrderState,
    OrderType,
    RiskDecision,
    RuleCheck,
    RuleResult,
    Side,
    TradeIntent,
    TradingAccount,
)
from .policy import TradingPolicy

_PASS = RuleResult.PASS
_FAIL = RuleResult.FAIL
_SKIP = RuleResult.SKIP


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _today_str() -> str:
    return _now_utc().date().isoformat()


def _nav(account: TradingAccount, conn: sqlite3.Connection) -> float:
    """NAV = cash + sum of position market values; falls back to cost if no market price (0201)."""
    rows = conn.execute(
        "SELECT qty, avg_cost, market_value FROM position_snapshots WHERE account_id=?",
        (account.account_id,),
    ).fetchall()
    pos_value = 0.0
    for r in rows:
        mv = r["market_value"] if "market_value" in r.keys() else None
        if mv is not None:
            pos_value += float(mv)
        else:
            pos_value += float(r["qty"] or 0) * float(r["avg_cost"] or 0)
    return account.current_cash + pos_value


def _position_qty(account_id: str, symbol: str, conn: sqlite3.Connection) -> float:
    row = conn.execute(
        "SELECT qty FROM position_snapshots WHERE account_id=? AND symbol=?",
        (account_id, symbol),
    ).fetchone()
    return float(row["qty"]) if row else 0.0


def _position_value(account_id: str, symbol: str, conn: sqlite3.Connection) -> float:
    """Return market value of symbol position; falls back to cost basis (0201)."""
    row = conn.execute(
        "SELECT qty, avg_cost, market_value FROM position_snapshots WHERE account_id=? AND symbol=?",
        (account_id, symbol),
    ).fetchone()
    if not row:
        return 0.0
    mv = row["market_value"] if "market_value" in row.keys() else None
    if mv is not None:
        return float(mv)
    return float(row["qty"] or 0) * float(row["avg_cost"] or 0)


def _daily_orders_count(account_id: str, conn: sqlite3.Connection) -> int:
    today = _today_str()
    row = conn.execute(
        "SELECT COUNT(*) as n FROM orders WHERE account_id=? AND DATE(submitted_at)=?",
        (account_id, today),
    ).fetchone()
    return int(row["n"]) if row else 0


def _daily_notional(account_id: str, conn: sqlite3.Connection) -> float:
    today = _today_str()
    row = conn.execute(
        "SELECT SUM(qty*price) as t FROM fills WHERE account_id=? AND DATE(filled_at)=?",
        (account_id, today),
    ).fetchone()
    return float(row["t"] or 0) if row else 0.0


def _open_buy_notional(
    account_id: str,
    conn: sqlite3.Connection,
    symbol: Optional[str] = None,
    exclude_order_id: Optional[str] = None,
) -> float:
    """Sum of remaining committed cash for open BUY/BUY_TO_CLOSE orders (0211).

    exclude_order_id: exclude this order from the sum to avoid double-counting
    when re-evaluating an order's own reservation (0220).
    """
    sql = """SELECT SUM((COALESCE(quantity,0) - COALESCE(fill_qty,0)) * COALESCE(limit_price,0)) AS t
             FROM orders
             WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')
               AND side IN ('BUY','BUY_TO_CLOSE')"""
    params: list = [account_id]
    if symbol:
        sql += " AND symbol=?"
        params.append(symbol)
    if exclude_order_id:
        sql += " AND order_id != ?"
        params.append(exclude_order_id)
    row = conn.execute(sql, params).fetchone()
    return float(row["t"] or 0) if row else 0.0


def _open_sell_qty(
    account_id: str,
    symbol: str,
    conn: sqlite3.Connection,
    exclude_order_id: Optional[str] = None,
) -> float:
    """Remaining qty committed to open SELL/SELL_TO_OPEN orders for a symbol (0211).

    exclude_order_id: exclude this order to avoid double-counting (0220).
    """
    sql = """SELECT SUM(COALESCE(quantity,0) - COALESCE(fill_qty,0)) AS t
             FROM orders
             WHERE account_id=? AND symbol=?
               AND state IN ('WORKING','PARTIALLY_FILLED')
               AND side IN ('SELL','SELL_TO_OPEN')"""
    params: list = [account_id, symbol]
    if exclude_order_id:
        sql += " AND order_id != ?"
        params.append(exclude_order_id)
    row = conn.execute(sql, params).fetchone()
    return float(row["t"] or 0) if row else 0.0


def _open_sell_notional(
    account_id: str,
    conn: sqlite3.Connection,
    exclude_order_id: Optional[str] = None,
) -> float:
    """Sum of remaining gross notional for open SELL/SELL_TO_OPEN orders (0223).

    Included in MAX_DAILY_NOTIONAL so total daily turnover (buy + sell) is capped.
    exclude_order_id: exclude this order to avoid double-counting (0220).
    """
    sql = """SELECT SUM((COALESCE(quantity,0) - COALESCE(fill_qty,0)) * COALESCE(limit_price,0)) AS t
             FROM orders
             WHERE account_id=? AND state IN ('WORKING','PARTIALLY_FILLED')
               AND side IN ('SELL','SELL_TO_OPEN')"""
    params: list = [account_id]
    if exclude_order_id:
        sql += " AND order_id != ?"
        params.append(exclude_order_id)
    row = conn.execute(sql, params).fetchone()
    return float(row["t"] or 0) if row else 0.0


def _open_contracts(account_id: str, symbol: str, conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """SELECT COALESCE(SUM(f.qty),0) as total
           FROM fills f
           JOIN orders o ON f.order_id=o.order_id
           WHERE f.account_id=? AND f.symbol=? AND o.contracts IS NOT NULL
             AND f.side='SELL_TO_OPEN'""",
        (account_id, symbol),
    ).fetchone()
    closed = conn.execute(
        """SELECT COALESCE(SUM(f.qty),0) as total
           FROM fills f
           JOIN orders o ON f.order_id=o.order_id
           WHERE f.account_id=? AND f.symbol=? AND o.contracts IS NOT NULL
             AND f.side='BUY_TO_CLOSE'""",
        (account_id, symbol),
    ).fetchone()
    open_qty = float(row["total"] if row else 0)
    closed_qty = float(closed["total"] if closed else 0)
    return max(0, int(open_qty - closed_qty))


def _stale_position_symbols(
    account_id: str,
    conn: sqlite3.Connection,
    stale_minutes: int,
) -> list[str]:
    """Return symbols with stale market price marks (0221).

    A position is stale only when market_price HAS been set (at least one refresh ran)
    but price_as_of is missing or older than stale_minutes. Positions that have never
    been marked (market_price IS NULL) are considered unpriced, not stale — they exist
    in new accounts where no refresh cycle has run yet.
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
            continue  # never refreshed — unpriced, not stale
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
    return stale


def evaluate(
    intent: TradeIntent,
    policy: TradingPolicy,
    account: TradingAccount,
    conn: sqlite3.Connection,
    strict_all: bool = False,
    exclude_order_id: Optional[str] = None,
    phase: str = "PRE_ORDER",
) -> RiskDecision:
    """Run all pre-trade risk checks. Fail-fast unless strict_all=True.

    exclude_order_id: when re-evaluating an existing WORKING order (phase='PRE_FILL'),
        pass the order's ID to exclude its own reservation from notional/qty helpers,
        preventing double-counting (0220).
    phase: 'PRE_ORDER' (first approval) or 'PRE_FILL' (retry fill revalidation). Persisted
        to risk_decisions.phase for audit (0220).
    """
    checks: list[RuleCheck] = []
    rejected = False

    def add(check: RuleCheck) -> bool:
        nonlocal rejected
        checks.append(check)
        if check.result == _FAIL:
            rejected = True
        return check.result != _FAIL

    # ── 0. RISK_STATE_STALE ── fail-closed if any position mark is stale (0221) ─
    if account.account_id:
        stale_minutes = policy.halt_on_data_stale_minutes()
        stale_symbols = _stale_position_symbols(account.account_id, conn, stale_minutes)
        if stale_symbols:
            add(RuleCheck(
                rule="RISK_STATE_STALE",
                result=_FAIL,
                reason=f"stale market price for positions: {stale_symbols} (limit {stale_minutes} min)",
            ))
            return _finalize(intent.intent_id, checks, conn, policy, account, _nav(account, conn), phase=phase)

    # Precompute shared values
    nav = _nav(account, conn)
    current_pos_qty = _position_qty(account.account_id, intent.symbol, conn)
    current_pos_value = _position_value(account.account_id, intent.symbol, conn)
    trade_qty = intent.quantity or 0.0
    trade_cost = trade_qty * intent.limit_price

    # ── 1. TRADING_ENABLED ────────────────────────────────────────────────────
    ok = add(RuleCheck(
        rule="TRADING_ENABLED",
        result=_PASS if policy.trading_enabled() else _FAIL,
        reason=None if policy.trading_enabled() else "circuit_breakers.trading_enabled is false",
    ))
    if not ok and not strict_all:
        return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)

    # ── 2. VALID_ACCOUNT ──────────────────────────────────────────────────────
    acct_row = conn.execute(
        "SELECT account_id FROM trading_accounts WHERE account_id=? AND trading_enabled=1",
        (account.account_id,),
    ).fetchone()
    ok = add(RuleCheck(
        rule="VALID_ACCOUNT",
        result=_PASS if acct_row else _FAIL,
        reason=None if acct_row else f"account {account.account_id!r} not found or disabled",
    ))
    if not ok and not strict_all:
        return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)

    # ── 3. INTENT_NOT_EXPIRED ─────────────────────────────────────────────────
    expired = intent.is_expired()
    ok = add(RuleCheck(
        rule="INTENT_NOT_EXPIRED",
        result=_FAIL if expired else _PASS,
        reason=f"valid_until={intent.valid_until} is in the past" if expired else None,
    ))
    if not ok and not strict_all:
        return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)

    # ── 4. NO_DUPLICATE_INTENT ────────────────────────────────────────────────
    if intent.recommendation_id is not None:
        dup = conn.execute(
            """SELECT intent_id FROM trade_intents
               WHERE recommendation_id=? AND status IN ('APPROVED','FILLED')
                 AND intent_id != ?""",
            (intent.recommendation_id, intent.intent_id),
        ).fetchone()
        ok = add(RuleCheck(
            rule="NO_DUPLICATE_INTENT",
            result=_FAIL if dup else _PASS,
            reason=f"recommendation {intent.recommendation_id} already has intent {dup['intent_id']}" if dup else None,
        ))
        if not ok and not strict_all:
            return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)
    else:
        add(RuleCheck(rule="NO_DUPLICATE_INTENT", result=_SKIP, reason="no recommendation_id"))

    # ── 5. INSTRUMENT_ALLOWED ─────────────────────────────────────────────────
    allowed = True
    reason_ia = None
    if intent.instrument_type == InstrumentType.EQUITY:
        if intent.side == Side.BUY and not policy.buy_allowed():
            allowed = False
            reason_ia = "equities.buy_allowed is false"
        elif intent.side == Side.SELL and not policy.sell_allowed():
            allowed = False
            reason_ia = "equities.sell_allowed is false"
    elif intent.instrument_type == InstrumentType.OPTION:
        if intent.side == Side.SELL_TO_OPEN and not policy.covered_calls_allowed():
            allowed = False
            reason_ia = "options.covered_calls_allowed is false"
    ok = add(RuleCheck(
        rule="INSTRUMENT_ALLOWED",
        result=_PASS if allowed else _FAIL,
        reason=reason_ia,
    ))
    if not ok and not strict_all:
        return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)

    # ── 6. NO_MARKET_ORDER ────────────────────────────────────────────────────
    is_market = intent.order_type == OrderType.MARKET
    market_allowed = policy.market_orders_allowed()
    ok = add(RuleCheck(
        rule="NO_MARKET_ORDER",
        result=_PASS if (not is_market or market_allowed) else _FAIL,
        reason="MARKET orders are not permitted by policy" if (is_market and not market_allowed) else None,
    ))
    if not ok and not strict_all:
        return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)

    # ── 7. SUFFICIENT_CASH ────────────────────────────────────────────────────
    if intent.side in (Side.BUY, Side.BUY_TO_CLOSE):
        reserved = _open_buy_notional(account.account_id, conn, exclude_order_id=exclude_order_id)
        available_cash = account.current_cash - reserved
        cash_after = available_cash - trade_cost
        min_cash = max(
            policy.min_cash_pct() / 100.0 * nav,
            policy.min_cash_abs(),
        )
        ok = add(RuleCheck(
            rule="SUFFICIENT_CASH",
            result=_PASS if cash_after >= min_cash else _FAIL,
            limit=round(min_cash, 2),
            before=round(available_cash, 2),
            after=round(cash_after, 2),
            reason=None if cash_after >= min_cash else f"available cash after trade ${cash_after:.2f} < minimum ${min_cash:.2f} (${reserved:.2f} reserved by open orders)",
        ))
        if not ok and not strict_all:
            return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)
    else:
        add(RuleCheck(rule="SUFFICIENT_CASH", result=_SKIP, reason="sell order does not require cash"))

    # ── 8. MAX_POSITION_WEIGHT ────────────────────────────────────────────────
    if intent.side == Side.BUY and nav > 0:
        open_buy_sym = _open_buy_notional(account.account_id, conn, intent.symbol, exclude_order_id=exclude_order_id)
        weight_before = current_pos_value / nav * 100
        weight_after = (current_pos_value + open_buy_sym + trade_cost) / nav * 100
        limit = policy.max_single_position_pct()
        ok = add(RuleCheck(
            rule="MAX_POSITION_WEIGHT",
            result=_PASS if weight_after <= limit else _FAIL,
            limit=limit,
            before=round(weight_before, 2),
            after=round(weight_after, 2),
            reason=None if weight_after <= limit else f"position weight {weight_after:.1f}% > limit {limit}%",
        ))
        if not ok and not strict_all:
            return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)
    else:
        add(RuleCheck(rule="MAX_POSITION_WEIGHT", result=_SKIP, reason="not a BUY or nav=0"))

    # ── 9. MAX_NEW_POSITION_WEIGHT ────────────────────────────────────────────
    if intent.side == Side.BUY and current_pos_qty == 0 and nav > 0:
        new_weight = trade_cost / nav * 100
        limit = policy.max_new_position_pct()
        ok = add(RuleCheck(
            rule="MAX_NEW_POSITION_WEIGHT",
            result=_PASS if new_weight <= limit else _FAIL,
            limit=limit,
            before=0.0,
            after=round(new_weight, 2),
            reason=None if new_weight <= limit else f"new position weight {new_weight:.1f}% > limit {limit}%",
        ))
        if not ok and not strict_all:
            return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)
    else:
        add(RuleCheck(rule="MAX_NEW_POSITION_WEIGHT", result=_SKIP, reason="not a new position or not a BUY"))

    # ── 10. MAX_DAILY_NOTIONAL ────────────────────────────────────────────────
    # Includes both open BUY and open SELL notional for total turnover cap (0223)
    if nav > 0:
        filled_notional = _daily_notional(account.account_id, conn)
        open_buy = _open_buy_notional(account.account_id, conn, exclude_order_id=exclude_order_id)
        open_sell = _open_sell_notional(account.account_id, conn, exclude_order_id=exclude_order_id)
        open_notional = open_buy + open_sell
        daily_notional_before = filled_notional + open_notional
        daily_notional_after = daily_notional_before + trade_cost
        limit_notional = policy.max_daily_notional_pct() / 100.0 * nav
        ok = add(RuleCheck(
            rule="MAX_DAILY_NOTIONAL",
            result=_PASS if daily_notional_after <= limit_notional else _FAIL,
            limit=round(limit_notional, 2),
            before=round(daily_notional_before, 2),
            after=round(daily_notional_after, 2),
            reason=None if daily_notional_after <= limit_notional
                else f"daily notional ${daily_notional_after:.0f} > limit ${limit_notional:.0f} (includes ${open_notional:.0f} in open orders)",
        ))
        if not ok and not strict_all:
            return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)
    else:
        add(RuleCheck(rule="MAX_DAILY_NOTIONAL", result=_SKIP, reason="nav=0"))

    # ── 11. MAX_ORDERS_PER_DAY ────────────────────────────────────────────────
    orders_today = _daily_orders_count(account.account_id, conn)
    limit_orders = policy.max_orders_per_day()
    ok = add(RuleCheck(
        rule="MAX_ORDERS_PER_DAY",
        result=_PASS if orders_today < limit_orders else _FAIL,
        limit=float(limit_orders),
        before=float(orders_today),
        after=float(orders_today + 1),
        reason=None if orders_today < limit_orders
            else f"orders today {orders_today} >= limit {limit_orders}",
    ))
    if not ok and not strict_all:
        return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)

    # ── 12. SELL_QUANTITY_COVERED ─────────────────────────────────────────────
    if intent.side in (Side.SELL, Side.BUY_TO_CLOSE):
        pending_sells = _open_sell_qty(account.account_id, intent.symbol, conn, exclude_order_id=exclude_order_id)
        available_qty = current_pos_qty - pending_sells
        covered = available_qty >= trade_qty
        ok = add(RuleCheck(
            rule="SELL_QUANTITY_COVERED",
            result=_PASS if covered else _FAIL,
            limit=trade_qty,
            before=available_qty,
            after=available_qty - trade_qty if covered else None,
            reason=None if covered else f"available qty {available_qty} < sell qty {trade_qty} ({pending_sells} already committed to open sell orders)",
        ))
        if not ok and not strict_all:
            return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)
    else:
        add(RuleCheck(rule="SELL_QUANTITY_COVERED", result=_SKIP, reason="not a sell order"))

    # ── 13. NO_NAKED_OPTIONS ─────────────────────────────────────────────────
    if intent.side == Side.SELL_TO_OPEN:
        contracts = intent.contracts or 1
        underlying_qty = _position_qty(account.account_id, intent.symbol, conn)
        required = contracts * 100
        ok = add(RuleCheck(
            rule="NO_NAKED_OPTIONS",
            result=_PASS if underlying_qty >= required else _FAIL,
            limit=float(required),
            before=underlying_qty,
            reason=None if underlying_qty >= required
                else f"underlying shares {underlying_qty} < required {required} for {contracts} contract(s)",
        ))
        if not ok and not strict_all:
            return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)
    else:
        add(RuleCheck(rule="NO_NAKED_OPTIONS", result=_SKIP, reason="not SELL_TO_OPEN"))

    # ── 14. MAX_CONTRACTS_PER_SYMBOL ─────────────────────────────────────────
    if intent.instrument_type == InstrumentType.OPTION and intent.side == Side.SELL_TO_OPEN:
        open_c = _open_contracts(account.account_id, intent.symbol, conn)
        requested_c = intent.contracts or 1
        limit_c = policy.max_contracts_per_symbol()
        ok = add(RuleCheck(
            rule="MAX_CONTRACTS_PER_SYMBOL",
            result=_PASS if (open_c + requested_c) <= limit_c else _FAIL,
            limit=float(limit_c),
            before=float(open_c),
            after=float(open_c + requested_c),
            reason=None if (open_c + requested_c) <= limit_c
                else f"open+requested contracts {open_c}+{requested_c} > limit {limit_c}",
        ))
        if not ok and not strict_all:
            return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)
    else:
        add(RuleCheck(rule="MAX_CONTRACTS_PER_SYMBOL", result=_SKIP, reason="not an option sell"))

    # ── 15. DATA_FRESHNESS ────────────────────────────────────────────────────
    # Options: check option_quote_snapshots age. Equities: check position price_as_of (0222).
    stale_minutes = policy.halt_on_data_stale_minutes()
    if intent.instrument_type == InstrumentType.OPTION:
        row = conn.execute(
            """SELECT captured_at FROM option_quote_snapshots
               WHERE ticker=? AND strike=? AND expiration=?
               ORDER BY captured_at DESC LIMIT 1""",
            (intent.symbol, intent.strike, intent.expiration),
        ).fetchone()
        if row:
            age_minutes = (_now_utc().timestamp() - float(row["captured_at"])) / 60
            fresh = age_minutes <= stale_minutes
            add(RuleCheck(
                rule="DATA_FRESHNESS",
                result=_PASS if fresh else _FAIL,
                limit=float(stale_minutes),
                before=round(age_minutes, 1),
                reason=None if fresh else f"option quote is {age_minutes:.0f} min old > limit {stale_minutes} min",
            ))
        else:
            add(RuleCheck(rule="DATA_FRESHNESS", result=_SKIP, reason="no option quote on file"))
    else:
        # Equity: check price_as_of on the position if held (0222)
        pos_row = conn.execute(
            "SELECT price_as_of FROM position_snapshots WHERE account_id=? AND symbol=?",
            (account.account_id, intent.symbol),
        ).fetchone()
        if pos_row and pos_row["price_as_of"]:
            try:
                price_ts = datetime.fromisoformat(
                    pos_row["price_as_of"].replace("Z", "+00:00")
                ).timestamp()
                age_minutes = (_now_utc().timestamp() - price_ts) / 60
                fresh = age_minutes <= stale_minutes
                add(RuleCheck(
                    rule="DATA_FRESHNESS",
                    result=_PASS if fresh else _FAIL,
                    limit=float(stale_minutes),
                    before=round(age_minutes, 1),
                    reason=None if fresh else f"equity mark is {age_minutes:.0f} min old > limit {stale_minutes} min",
                ))
            except Exception:
                add(RuleCheck(rule="DATA_FRESHNESS", result=_SKIP, reason="could not parse price_as_of"))
        else:
            add(RuleCheck(rule="DATA_FRESHNESS", result=_SKIP, reason="no equity mark on file (new position)"))

    # ── 16. NO_EARNINGS_CONFLICT ──────────────────────────────────────────────
    if intent.instrument_type == InstrumentType.OPTION and intent.expiration:
        earnings = conn.execute(
            """SELECT event_date FROM event_calendar
               WHERE ticker=? AND event_type='earnings'
                 AND event_date > ? AND event_date <= ?
               LIMIT 1""",
            (intent.symbol, _today_str(), intent.expiration),
        ).fetchone()
        ok = add(RuleCheck(
            rule="NO_EARNINGS_CONFLICT",
            result=_FAIL if earnings else _PASS,
            reason=f"earnings event on {earnings['event_date']} before expiry {intent.expiration}" if earnings else None,
        ))
        if not ok and not strict_all:
            return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)
    else:
        add(RuleCheck(rule="NO_EARNINGS_CONFLICT", result=_SKIP, reason="equity or no expiration"))

    # ── 17. MAX_DAILY_LOSS ────────────────────────────────────────────────────
    today = _today_str()
    loss_row = conn.execute(
        """SELECT COALESCE(SUM(-realized_pnl), 0) as total_loss
           FROM fills
           WHERE account_id=? AND DATE(filled_at)=? AND realized_pnl < 0""",
        (account.account_id, today),
    ).fetchone()
    daily_loss = float(loss_row["total_loss"] or 0)
    max_daily_loss_abs = policy.max_daily_loss_pct() / 100.0 * account.starting_capital
    ok = add(RuleCheck(
        rule="MAX_DAILY_LOSS",
        result=_PASS if daily_loss < max_daily_loss_abs else _FAIL,
        limit=round(max_daily_loss_abs, 2),
        before=round(daily_loss, 2),
        reason=None if daily_loss < max_daily_loss_abs
            else f"daily loss ${daily_loss:.2f} >= limit ${max_daily_loss_abs:.2f}",
    ))
    if not ok and not strict_all:
        return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)

    # ── 18. MAX_DRAWDOWN ─────────────────────────────────────────────────────
    acct_row = conn.execute(
        "SELECT nav_high_water FROM trading_accounts WHERE account_id=?",
        (account.account_id,),
    ).fetchone()
    peak = None
    if acct_row and "nav_high_water" in acct_row.keys():
        peak = acct_row["nav_high_water"]
    peak = float(peak) if peak else account.starting_capital
    drawdown_pct = max(0.0, (peak - nav) / peak * 100) if peak > 0 else 0.0
    limit_dd = policy.max_drawdown_pct()
    ok = add(RuleCheck(
        rule="MAX_DRAWDOWN",
        result=_PASS if drawdown_pct <= limit_dd else _FAIL,
        limit=limit_dd,
        before=round(drawdown_pct, 2),
        reason=None if drawdown_pct <= limit_dd
            else f"drawdown {drawdown_pct:.1f}% > limit {limit_dd}%",
    ))
    if not ok and not strict_all:
        return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)

    # ── 19. MIN_LIMIT_PRICE ──────────────────────────────────────────────────
    if intent.limit_price is not None:
        min_lim = policy.min_limit_price()
        above_min = intent.limit_price >= min_lim
        add(RuleCheck(
            rule="MIN_LIMIT_PRICE",
            result=_PASS if above_min else _FAIL,
            limit=min_lim,
            before=intent.limit_price,
            reason=None if above_min
                else f"limit_price ${intent.limit_price:.4f} < minimum ${min_lim:.4f}",
        ))
    else:
        add(RuleCheck(rule="MIN_LIMIT_PRICE", result=_SKIP, reason="no limit_price on intent"))

    return _finalize(intent.intent_id, checks, conn, policy, account, nav, phase=phase)


def _finalize(
    intent_id: str,
    checks: list[RuleCheck],
    conn: sqlite3.Connection,
    policy: Optional[TradingPolicy] = None,
    account: Optional[TradingAccount] = None,
    nav: Optional[float] = None,
    phase: str = "PRE_ORDER",
) -> RiskDecision:
    """Persist risk decision with provenance and return RiskDecision (0204)."""
    any_fail = any(c.result == _FAIL for c in checks)
    decision = "REJECTED" if any_fail else "APPROVED"
    evaluated_at = datetime.now(timezone.utc).isoformat()
    decision_id = str(uuid.uuid4())

    policy_version = policy.policy_version if policy else None
    policy_hash = policy.policy_hash() if policy else None
    account_cash = account.current_cash if account else None
    account_nav = nav

    try:
        conn.execute(
            """INSERT INTO risk_decisions
               (intent_id, decision, checks_json, evaluated_at,
                uuid_id, policy_version, policy_hash, account_cash_at_eval, account_nav_at_eval,
                phase)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                intent_id, decision,
                json.dumps([c.to_dict() for c in checks]),
                evaluated_at, decision_id,
                policy_version, policy_hash, account_cash, account_nav,
                phase,
            ),
        )
    except Exception:
        # Fallback for schemas without the phase column yet
        conn.execute(
            """INSERT INTO risk_decisions
               (intent_id, decision, checks_json, evaluated_at,
                uuid_id, policy_version, policy_hash, account_cash_at_eval, account_nav_at_eval)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                intent_id, decision,
                json.dumps([c.to_dict() for c in checks]),
                evaluated_at, decision_id,
                policy_version, policy_hash, account_cash, account_nav,
            ),
        )
    conn.commit()

    return RiskDecision(
        decision_id=decision_id,
        intent_id=intent_id,
        decision=decision,
        checks=checks,
        evaluated_at=evaluated_at,
    )
