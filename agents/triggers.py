from __future__ import annotations
"""Deterministic trigger detection — no LLM calls.

detect_triggers() maps portfolio state to which agents should run and why.
Each TriggerEvent carries enough context that the receiving agent doesn't
need to re-derive why it was called.

DB reads are allowed (price history, lots, CC positions, macro scores) — the
function has no write side-effects and is safe to call after any data refresh.
"""
import datetime
import json
import math
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from .contracts import PortfolioSnapshot

_DB = Path(__file__).resolve().parent.parent / "out" / "investment.db"


@dataclass
class TriggerEvent:
    trigger_type: str           # layer_drift | price_move | nav_impact | macro_score_change |
                                # cc_eligible | cc_mgmt_dte | tax_lt_crossover | tax_loss_harvest |
                                # layer_underweight | portfolio_scope
    agent_type: str             # which agent should handle this trigger
    trigger_key: str | None = None    # human-readable identifier (e.g. "L1", ticker)
    ticker: str | None = None         # None for portfolio-scope triggers
    trigger_value: float | None = None  # the metric value that crossed the threshold
    context: dict = field(default_factory=dict)  # extra detail for the receiving agent


# ── DB helpers (read-only) ─────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection | None:
    if not _DB.exists():
        return None
    conn = sqlite3.connect(str(_DB), timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def _load_price_history(tickers: list[str], days: int = 22) -> dict[str, list[float]]:
    """Return {ticker: [price_oldest … price_newest]} for the last `days` trading days."""
    conn = _connect()
    if not conn:
        return {}
    result: dict[str, list[float]] = {}
    for ticker in tickers:
        rows = conn.execute(
            "SELECT price FROM holding_day WHERE ticker=? ORDER BY day DESC LIMIT ?",
            (ticker, days),
        ).fetchall()
        if rows:
            result[ticker] = [r[0] for r in reversed(rows)]
    conn.close()
    return result


def _load_today_changes(tickers: list[str]) -> dict[str, float]:
    """Return {ticker: change_pct} for today's session from holding_day."""
    conn = _connect()
    if not conn:
        return {}
    today = datetime.date.today().isoformat()
    rows = conn.execute(
        f"SELECT ticker, change_pct FROM holding_day WHERE day=? AND ticker IN ({','.join('?'*len(tickers))})",
        (today, *tickers),
    ).fetchall()
    conn.close()
    return {r["ticker"]: r["change_pct"] for r in rows}


def _load_macro_score_history(tickers: list[str]) -> dict[str, list[dict]]:
    """Return last 2 score snapshots per ticker {ticker: [older, newer]}."""
    conn = _connect()
    if not conn:
        return {}
    result: dict[str, list[dict]] = {}
    for ticker in tickers:
        rows = conn.execute(
            "SELECT scores, scored_at FROM holding_macro_scores_history "
            "WHERE ticker=? ORDER BY scored_at DESC LIMIT 2",
            (ticker,),
        ).fetchall()
        if len(rows) >= 2:
            result[ticker] = [json.loads(r["scores"]) for r in reversed(rows)]
    conn.close()
    return result


def _load_cost_lots(tickers: list[str]) -> dict[str, list[dict]]:
    """Return {ticker: [lot dicts]} from cost_lots."""
    conn = _connect()
    if not conn:
        return {}
    result: dict[str, list[dict]] = {}
    for ticker in tickers:
        rows = conn.execute(
            "SELECT ticker, shares, cost_per_share, purchase_date "
            "FROM cost_lots WHERE ticker=?",
            (ticker,),
        ).fetchall()
        result[ticker] = [dict(r) for r in rows]
    conn.close()
    return result


def _load_open_cc_positions() -> list[dict]:
    """Return open covered call positions with DTE computed."""
    conn = _connect()
    if not conn:
        return []
    today = datetime.date.today()
    rows = conn.execute(
        "SELECT ticker, contracts, strike, expiry FROM cc_positions WHERE status='open'"
    ).fetchall()
    conn.close()
    positions = []
    for r in rows:
        try:
            exp = datetime.date.fromisoformat(r["expiry"])
            dte = (exp - today).days
            positions.append({"ticker": r["ticker"], "strike": r["strike"],
                               "expiry": r["expiry"], "dte": dte})
        except (ValueError, TypeError):
            pass
    return positions


def _load_layer_weight_history(days: int = 5) -> dict[str, list[float]]:
    """Return {layer_label: [weight_pct_oldest … newest]} for last N days."""
    conn = _connect()
    if not conn:
        return {}
    result: dict[str, list[float]] = {}
    rows = conn.execute(
        "SELECT day, layer, weight_pct FROM layer_day ORDER BY day DESC LIMIT ?",
        (days * 10,),  # enough rows to cover all layers × days
    ).fetchall()
    conn.close()
    # Group by layer, keep newest `days` entries
    by_layer: dict[str, list[tuple[str, float]]] = {}
    for r in rows:
        by_layer.setdefault(r["layer"], []).append((r["day"], r["weight_pct"]))
    for layer, entries in by_layer.items():
        entries.sort()  # oldest first
        result[layer] = [e[1] for e in entries[-days:]]
    return result


# ── HV calculation ─────────────────────────────────────────────────────────────

def _hv20_daily(prices: list[float]) -> float | None:
    """Annualised 20-day historical volatility from a price series (oldest→newest)."""
    if len(prices) < 21:
        return None
    log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices))]
    last_20 = log_returns[-20:]
    mean = sum(last_20) / len(last_20)
    variance = sum((r - mean) ** 2 for r in last_20) / (len(last_20) - 1)
    return math.sqrt(variance * 252)


# ── Layer number extractor ─────────────────────────────────────────────────────

def _layer_num(label: str) -> int | None:
    """Extract layer number from a label like 'Layer 3: L3 Compounders'."""
    try:
        return int(label.split()[1].rstrip(":"))
    except (IndexError, ValueError):
        return None


# ── Main entry point ───────────────────────────────────────────────────────────

def detect_triggers(snapshot: PortfolioSnapshot) -> list[TriggerEvent]:
    """Return all triggers active for the given snapshot."""
    from strategy_config import (
        LAYER_TARGETS, DRIFT_THRESHOLD,
        TRIGGER_PRICE_MOVE_Z, TRIGGER_NAV_IMPACT_PCT,
        TRIGGER_MACRO_SCORE_CHANGE, TRIGGER_CC_MGMT_DTE,
        TRIGGER_TAX_LT_WINDOW_MIN, TRIGGER_TAX_LT_WINDOW_MAX,
        TRIGGER_TAX_LOSS_MIN, TRIGGER_LAYER_UNDERWEIGHT_DAYS,
    )

    triggers: list[TriggerEvent] = []
    tickers = [h.ticker for h in snapshot.holdings]
    today = datetime.date.today()

    # ── Layer drift → Portfolio Guardian ──────────────────────────────────────
    for layer_num, weight_pct in snapshot.layer_weights.items():
        target = LAYER_TARGETS.get(layer_num, 0.0)
        drift = weight_pct - target
        if abs(drift) >= DRIFT_THRESHOLD:
            triggers.append(TriggerEvent(
                trigger_type="layer_drift",
                agent_type="portfolio_guardian",
                trigger_key=f"L{layer_num}",
                ticker=None,
                trigger_value=round(drift, 2),
                context={"layer": layer_num, "target": target,
                         "actual": round(weight_pct, 2), "drift_pp": round(drift, 2)},
            ))

    # ── Price move Z-score → Portfolio Guardian ────────────────────────────────
    price_history = _load_price_history(tickers, days=22)
    today_changes = _load_today_changes(tickers)

    for h in snapshot.holdings:
        prices = price_history.get(h.ticker)
        hv_annual = _hv20_daily(prices) if prices else None
        daily_return_pct = today_changes.get(h.ticker)
        if hv_annual and hv_annual > 0 and daily_return_pct is not None:
            hv_daily = hv_annual / math.sqrt(252)
            z = abs(daily_return_pct / 100) / hv_daily
            if z >= TRIGGER_PRICE_MOVE_Z:
                triggers.append(TriggerEvent(
                    trigger_type="price_move",
                    agent_type="portfolio_guardian",
                    trigger_key=h.ticker,
                    ticker=h.ticker,
                    trigger_value=round(z, 2),
                    context={"z_score": round(z, 2), "daily_return_pct": round(daily_return_pct, 2),
                             "hv20_annual": round(hv_annual * 100, 1)},
                ))

    # ── Position NAV impact → Portfolio Guardian ───────────────────────────────
    for h in snapshot.holdings:
        daily_return_pct = today_changes.get(h.ticker)
        if daily_return_pct is not None:
            nav_impact = (h.weight_pct / 100) * abs(daily_return_pct / 100) * 100
            if nav_impact >= TRIGGER_NAV_IMPACT_PCT:
                triggers.append(TriggerEvent(
                    trigger_type="nav_impact",
                    agent_type="portfolio_guardian",
                    trigger_key=h.ticker,
                    ticker=h.ticker,
                    trigger_value=round(nav_impact, 3),
                    context={"nav_impact_pct": round(nav_impact, 3),
                             "weight_pct": round(h.weight_pct, 2),
                             "daily_return_pct": round(daily_return_pct, 2)},
                ))

    # ── Macro score change → Portfolio Guardian ────────────────────────────────
    macro_history = _load_macro_score_history(tickers)
    _DIMS = ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk")

    for ticker, (older, newer) in macro_history.items():
        for dim in _DIMS:
            old_val = older.get(dim, {}).get("score") if isinstance(older.get(dim), dict) else older.get(dim)
            new_val = newer.get(dim, {}).get("score") if isinstance(newer.get(dim), dict) else newer.get(dim)
            if old_val is not None and new_val is not None:
                change = abs(new_val - old_val)
                if change >= TRIGGER_MACRO_SCORE_CHANGE:
                    triggers.append(TriggerEvent(
                        trigger_type="macro_score_change",
                        agent_type="portfolio_guardian",
                        trigger_key=f"{ticker}.{dim}",
                        ticker=ticker,
                        trigger_value=round(change, 1),
                        context={"dimension": dim, "old_score": old_val,
                                 "new_score": new_val, "change": round(change, 1)},
                    ))
                    break  # one trigger per ticker per cycle

    # ── CC eligibility (new opportunity) → Covered Call Agent ─────────────────
    _CC_MIN_SHARES = 100
    _CC_ELIGIBLE_LAYERS = {1, 2, 3}

    for h in snapshot.holdings:
        if h.layer in _CC_ELIGIBLE_LAYERS and h.shares >= _CC_MIN_SHARES:
            triggers.append(TriggerEvent(
                trigger_type="cc_eligible",
                agent_type="covered_call",
                trigger_key=h.ticker,
                ticker=h.ticker,
                trigger_value=float(h.shares),
                context={"shares": h.shares, "layer": h.layer,
                         "value": round(h.market_value, 2)},
            ))

    # ── CC management DTE → Covered Call Agent ────────────────────────────────
    open_ccs = _load_open_cc_positions()
    for pos in open_ccs:
        if pos["dte"] <= TRIGGER_CC_MGMT_DTE:
            triggers.append(TriggerEvent(
                trigger_type="cc_mgmt_dte",
                agent_type="covered_call",
                trigger_key=pos["ticker"],
                ticker=pos["ticker"],
                trigger_value=float(pos["dte"]),
                context={"dte": pos["dte"], "strike": pos["strike"],
                         "expiry": pos["expiry"]},
            ))

    # ── Tax lot LT crossover window → Tax Agent ───────────────────────────────
    cost_lots = _load_cost_lots(tickers)

    for ticker, lots in cost_lots.items():
        for lot in lots:
            try:
                purchase = datetime.date.fromisoformat(lot["purchase_date"])
            except (ValueError, TypeError):
                continue
            lt_date = purchase + datetime.timedelta(days=365)
            days_to_lt = (lt_date - today).days
            if TRIGGER_TAX_LT_WINDOW_MIN <= days_to_lt <= TRIGGER_TAX_LT_WINDOW_MAX:
                triggers.append(TriggerEvent(
                    trigger_type="tax_lt_crossover",
                    agent_type="tax",
                    trigger_key=ticker,
                    ticker=ticker,
                    trigger_value=float(days_to_lt),
                    context={"days_to_lt": days_to_lt, "purchase_date": lot["purchase_date"],
                             "lt_date": lt_date.isoformat(), "shares": lot["shares"],
                             "cost_per_share": lot["cost_per_share"]},
                ))
                break  # one trigger per ticker

    # ── Unrealized loss on ST lot → Tax Agent ────────────────────────────────
    price_by_ticker = {h.ticker: h.current_price for h in snapshot.holdings}
    for ticker, lots in cost_lots.items():
        current_price = price_by_ticker.get(ticker)
        if current_price is None:
            continue
        for lot in lots:
            try:
                purchase = datetime.date.fromisoformat(lot["purchase_date"])
            except (ValueError, TypeError):
                continue
            days_held = (today - purchase).days
            if days_held >= 365:
                continue  # already LT — tax agent handles ST losses
            loss = (current_price - lot["cost_per_share"]) * lot["shares"]
            if loss < -TRIGGER_TAX_LOSS_MIN:
                triggers.append(TriggerEvent(
                    trigger_type="tax_loss_harvest",
                    agent_type="tax",
                    trigger_key=ticker,
                    ticker=ticker,
                    trigger_value=round(loss, 2),
                    context={"unrealized_loss": round(loss, 2), "shares": lot["shares"],
                             "cost_per_share": lot["cost_per_share"],
                             "current_price": current_price, "days_held": days_held},
                ))
                break  # one trigger per ticker

    # ── Layer underweight for N consecutive days → Opportunity Hunter ──────────
    layer_history = _load_layer_weight_history(days=TRIGGER_LAYER_UNDERWEIGHT_DAYS + 1)

    for label, weights in layer_history.items():
        layer_num = _layer_num(label)
        if layer_num is None:
            continue
        target = LAYER_TARGETS.get(layer_num, 0.0)
        underweight_threshold = target - DRIFT_THRESHOLD
        # All recent weights must be below threshold
        recent = weights[-TRIGGER_LAYER_UNDERWEIGHT_DAYS:]
        if len(recent) >= TRIGGER_LAYER_UNDERWEIGHT_DAYS and all(
            w < underweight_threshold for w in recent
        ):
            avg_deficit = round(target - sum(recent) / len(recent), 2)
            triggers.append(TriggerEvent(
                trigger_type="layer_underweight",
                agent_type="opportunity_hunter",
                trigger_key=f"L{layer_num}",
                ticker=None,
                trigger_value=round(recent[-1], 2),
                context={"layer": layer_num, "target": target,
                         "current_weight": round(recent[-1], 2),
                         "avg_deficit_pp": avg_deficit,
                         "consecutive_days": TRIGGER_LAYER_UNDERWEIGHT_DAYS},
            ))

    # ── Thesis monitoring (daily portfolio sweep) ─────────────────────────────
    triggers.append(TriggerEvent(
        trigger_type="portfolio_scope",
        agent_type="thesis_monitor",
        trigger_key="thesis_daily",
        ticker=None,
        trigger_value=None,
        context={"total_value": snapshot.total_value},
    ))

    # ── Sell/Trim evaluation (daily portfolio sweep) ───────────────────────────
    triggers.append(TriggerEvent(
        trigger_type="portfolio_scope",
        agent_type="sell_trim",
        trigger_key="sell_trim_daily",
        ticker=None,
        trigger_value=None,
        context={"total_value": snapshot.total_value},
    ))

    # ── Portfolio-scope daily briefing (always fires) ─────────────────────────
    triggers.append(TriggerEvent(
        trigger_type="portfolio_scope",
        agent_type="briefing",
        trigger_key="daily",
        ticker=None,
        trigger_value=None,
        context={"total_value": snapshot.total_value},
    ))

    # ── Log for auditability ───────────────────────────────────────────────────
    for t in triggers:
        val = f" value={t.trigger_value}" if t.trigger_value is not None else ""
        print(f"[triggers] {t.trigger_type} → {t.agent_type}"
              f" key={t.trigger_key}{val}")

    return triggers
