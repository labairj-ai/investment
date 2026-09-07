from __future__ import annotations
"""Tax Agent — proactive lot-level tax timing and loss-harvest recommendations.

Runs as a portfolio-scope agent. Self-scans all cost lots rather than relying
on trigger_type from context (the trigger engine's job is to wake the agent;
the agent is authoritative on what it finds).

Two recommendation types:
  WAIT    — lot approaching LT crossover; hold to avoid ST tax on the gain
  HARVEST — ST lot with unrealized loss > threshold; offset available ST gains
  VETO    — lot has missing/zero cost basis; no LLM call, flag for manual fix
"""
import datetime
import sqlite3
from pathlib import Path

import agent_db
import ollama_client
from strategy_config import (
    TAX_ST_RATE, TAX_LT_RATE,
    TRIGGER_TAX_LT_WINDOW_MIN,
    TRIGGER_TAX_LT_WINDOW_MAX,
    TRIGGER_TAX_LOSS_MIN,
)

from .contracts import AgentContext, Recommendation
from .orchestrator import register_agent

_DB = Path(agent_db.DB_PATH)

# ── DB helpers ────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_DB), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _load_all_lots() -> list[dict]:
    """Return all rows from cost_lots as plain dicts."""
    if not _DB.exists():
        return []
    try:
        conn = _connect()
        rows = conn.execute(
            "SELECT id, ticker, shares, cost_per_share, purchase_date, notes "
            "FROM cost_lots ORDER BY ticker, purchase_date"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[tax] DB read error: {e}")
        return []


def _ytd_st_gains(year: str) -> float:
    """YTD short-term realized gains: sell_transactions ST + closed/expired CC income."""
    if not _DB.exists():
        return 0.0
    try:
        conn = _connect()
        sell_rows = conn.execute(
            "SELECT st_gain FROM sell_transactions "
            "WHERE strftime('%Y', sell_date) = ?", (year,)
        ).fetchall()
        st_from_sells = sum(r["st_gain"] or 0.0 for r in sell_rows)

        # CC premium income is always short-term ordinary income
        cc_rows = conn.execute(
            "SELECT net_premium FROM cc_positions "
            "WHERE status IN ('expired', 'closed') "
            "AND strftime('%Y', closed_date) = ? "
            "AND net_premium > 0", (year,)
        ).fetchall()
        st_from_cc = sum(r["net_premium"] or 0.0 for r in cc_rows)
        conn.close()
        return st_from_sells + st_from_cc
    except Exception as e:
        print(f"[tax] YTD gains query error: {e}")
        return 0.0


# ── LLM schema ────────────────────────────────────────────────────────────────

_WAIT_SCHEMA = {
    "type": "object",
    "properties": {
        "summary":       {"type": "string"},
        "action_risk":   {"type": "string"},
        "no_action_case": {"type": "string"},
    },
    "required": ["summary", "action_risk", "no_action_case"],
}

_HARVEST_SCHEMA = {
    "type": "object",
    "properties": {
        "summary":       {"type": "string"},
        "action_risk":   {"type": "string"},
        "no_action_case": {"type": "string"},
    },
    "required": ["summary", "action_risk", "no_action_case"],
}


def _llm_wait_narrative(
    ticker: str, days_to_lt: int, shares: float,
    current_price: float, unrealized_gain: float,
    avoidable_tax: float, lt_date: str,
) -> dict:
    prompt = (
        f"TAX TIMING ANALYSIS — {ticker}\n\n"
        f"This lot reaches long-term capital gains status in {days_to_lt} days ({lt_date}).\n"
        f"Shares: {shares:.4g} | Current price: ${current_price:.2f}\n"
        f"Unrealized gain: ${unrealized_gain:+,.0f}\n"
        f"Selling now vs waiting: ST rate {TAX_ST_RATE:.0%} → LT rate {TAX_LT_RATE:.0%}. "
        f"Incremental tax saved by waiting: ${avoidable_tax:,.0f} "
        f"(gain × {TAX_ST_RATE - TAX_LT_RATE:.0%} rate differential).\n\n"
        "Write a concise tax-timing summary. All dollar amounts above are final — do NOT "
        "recalculate or contradict them. Answer:\n"
        '{"summary":"<1-2 sentences: what the situation is and why waiting is the right move>",'
        '"action_risk":"<what could go wrong if the investor waits — e.g. stock drops, position '
        'expires worthless, opportunity cost>",'
        '"no_action_case":"<strongest reason to sell now despite the tax hit, 1 sentence>"}'
    )
    try:
        out = ollama_client.generate_structured(
            prompt=prompt,
            schema=_WAIT_SCHEMA,
            model="mlx-community/Qwen3.6-35B-A3B-4bit",
            temperature=0.2,
            num_predict=400,
            thinking=False,
            retries=2,
        )
        if isinstance(out, dict) and out.get("summary"):
            return out
    except Exception as e:
        print(f"[tax] LLM WAIT narrative failed: {e}")
    return {
        "summary": (
            f"{ticker} lot reaches LT status in {days_to_lt} days ({lt_date}). "
            f"Waiting saves ${avoidable_tax:,.0f} in incremental tax "
            f"(ST {TAX_ST_RATE:.0%} → LT {TAX_LT_RATE:.0%} on ${unrealized_gain:+,.0f} gain)."
        ),
        "action_risk": "Position could decline before the LT crossover date, reducing the gain being protected.",
        "no_action_case": "If you have an urgent need for liquidity or conviction has changed, the rate differential may be acceptable.",
    }


def _llm_harvest_narrative(
    ticker: str, unrealized_loss: float, shares: float,
    current_price: float, cost_basis: float,
    ytd_st_gains: float, tlh_benefit: float,
    wash_sale_start: str, wash_sale_end: str,
    lot_type: str = "ST",
) -> dict:
    rate_note = (
        f"ST loss (offsets ST gains at {TAX_ST_RATE:.0%})"
        if lot_type == "ST"
        else f"LT loss (offsets LT gains at {TAX_LT_RATE:.0%}; excess offsets ST gains)"
    )
    prompt = (
        f"TAX LOSS HARVEST ANALYSIS — {ticker}\n\n"
        f"Shares: {shares:.4g} | Cost basis: ${cost_basis:.2f} | Current price: ${current_price:.2f}\n"
        f"Unrealized loss: ${unrealized_loss:,.0f} ({rate_note})\n"
        f"YTD realized ST gains to offset: ${ytd_st_gains:,.0f}\n"
        f"Estimated tax savings from harvesting: ${tlh_benefit:,.0f}\n"
        f"Wash sale window: {wash_sale_start} to {wash_sale_end} "
        f"(do not buy substantially identical securities in this range)\n\n"
        "Write a concise tax-loss harvesting summary. All dollar amounts above are final — do NOT "
        "recalculate or contradict them. Answer:\n"
        '{"summary":"<1-2 sentences: what the harvest opportunity is and the dollar benefit>",'
        '"action_risk":"<key risks: wash sale trap, re-entry timing, losing upside if stock rebounds>",'
        '"no_action_case":"<strongest reason to not harvest now, 1 sentence>"}'
    )
    try:
        out = ollama_client.generate_structured(
            prompt=prompt,
            schema=_HARVEST_SCHEMA,
            model="mlx-community/Qwen3.6-35B-A3B-4bit",
            temperature=0.2,
            num_predict=400,
            thinking=False,
            retries=2,
        )
        if isinstance(out, dict) and out.get("summary"):
            return out
    except Exception as e:
        print(f"[tax] LLM HARVEST narrative failed: {e}")
    offset_note = "ST gains" if lot_type == "ST" else "LT gains (LT loss netting)"
    return {
        "summary": (
            f"{ticker} has an unrealized {lot_type} loss of ${abs(unrealized_loss):,.0f} that can offset "
            f"{offset_note}, saving ~${tlh_benefit:,.0f} in taxes."
        ),
        "action_risk": (
            f"Wash sale rule: avoid buying {ticker} or substantially identical securities "
            f"from {wash_sale_start} to {wash_sale_end}."
        ),
        "no_action_case": "If you expect the stock to rebound soon, harvesting sacrifices that upside for a limited tax benefit.",
    }


# ── Core logic ─────────────────────────────────────────────────────────────────

def _check_lt_crossover(
    lots: list[dict],
    price_map: dict[str, float],
    today: datetime.date,
) -> list[Recommendation]:
    """Return WAIT (or VETO) recs for lots approaching LT crossover."""
    recs: list[Recommendation] = []
    by_ticker: dict[str, list[dict]] = {}
    for lot in lots:
        by_ticker.setdefault(lot["ticker"], []).append(lot)

    for ticker, ticker_lots in by_ticker.items():
        soonest_lot: dict | None = None
        soonest_days: int | None = None

        for lot in ticker_lots:
            try:
                purchase = datetime.date.fromisoformat(lot["purchase_date"])
            except (ValueError, TypeError):
                continue
            lt_date = purchase + datetime.timedelta(days=365)
            days_to_lt = (lt_date - today).days
            if TRIGGER_TAX_LT_WINDOW_MIN <= days_to_lt <= TRIGGER_TAX_LT_WINDOW_MAX:
                if soonest_days is None or days_to_lt < soonest_days:
                    soonest_days = days_to_lt
                    soonest_lot = {**lot, "_lt_date": lt_date.isoformat(), "_days_to_lt": days_to_lt}

        if soonest_lot is None:
            continue

        # Missing cost basis → VETO, no LLM call
        if not soonest_lot.get("cost_per_share"):
            recs.append(Recommendation(
                ticker=ticker,
                action="VETO",
                recommendation_score=0,
                confidence=95,
                priority="high",
                why_now=(
                    f"{ticker} lot (purchased {soonest_lot['purchase_date']}) reaches LT status in "
                    f"{soonest_lot['_days_to_lt']} days but has no cost basis recorded — "
                    "cannot evaluate tax impact."
                ),
                rationale="Missing cost basis prevents any tax calculation. Enter the correct basis before taking action.",
                no_action_case="Cannot act without a valid cost basis.",
            ))
            continue

        current_price = price_map.get(ticker)
        shares = soonest_lot["shares"]
        cost = soonest_lot["cost_per_share"]
        lt_date_str = soonest_lot["_lt_date"]
        days_to_lt = soonest_lot["_days_to_lt"]

        if current_price is None or current_price <= 0:
            current_price = cost  # fallback: assume flat, gain = 0

        unrealized_gain = (current_price - cost) * shares
        # Avoidable tax = only the rate DIFFERENTIAL; selling at LT still pays LT tax
        avoidable_tax = max(unrealized_gain, 0) * (TAX_ST_RATE - TAX_LT_RATE)
        st_tax_cost = max(unrealized_gain, 0) * TAX_ST_RATE  # retained for payload transparency

        narrative = _llm_wait_narrative(
            ticker=ticker,
            days_to_lt=days_to_lt,
            shares=shares,
            current_price=current_price,
            unrealized_gain=unrealized_gain,
            avoidable_tax=avoidable_tax,
            lt_date=lt_date_str,
        )

        score = max(50, min(90, 50 + (45 - days_to_lt) * 2))  # urgency increases as deadline nears
        recs.append(Recommendation(
            ticker=ticker,
            action="WAIT",
            recommendation_score=score,
            confidence=85,
            priority="high" if days_to_lt <= 35 else "normal",
            why_now=(
                f"LT crossover in {days_to_lt} days ({lt_date_str}). "
                f"Unrealized gain: ${unrealized_gain:+,.0f}. "
                f"Incremental tax saved by waiting: ${avoidable_tax:,.0f} "
                f"(ST {TAX_ST_RATE:.0%} → LT {TAX_LT_RATE:.0%} rate differential)."
            ),
            rationale=narrative["summary"],
            counter_case=narrative["action_risk"],
            no_action_case=narrative["no_action_case"],
            action_payload={
                "lot_id": soonest_lot["id"],
                "purchase_date": soonest_lot["purchase_date"],
                "lt_date": lt_date_str,
                "days_to_lt": days_to_lt,
                "shares": shares,
                "cost_per_share": cost,
                "current_price": current_price,
                "unrealized_gain": round(unrealized_gain, 2),
                "avoidable_tax": round(avoidable_tax, 2),
                "st_tax_cost": round(st_tax_cost, 2),
                "st_tax_rate": TAX_ST_RATE,
                "lt_tax_rate": TAX_LT_RATE,
            },
            dependencies=[{
                "dependency_type": "PRICE",
                "dependency_key": ticker,
                "original_value": current_price,
                "tolerance": 0.05,
                "invalidating_event": "PRICE_THRESHOLD",
            }],
        ))

    return recs


def _check_tlh(
    lots: list[dict],
    price_map: dict[str, float],
    today: datetime.date,
    ytd_st_gains: float,
) -> list[Recommendation]:
    """Return HARVEST recs for ST and LT lots with offsettable losses."""
    if ytd_st_gains <= 0:
        return []  # nothing to offset

    recs: list[Recommendation] = []
    by_ticker: dict[str, list[dict]] = {}
    for lot in lots:
        by_ticker.setdefault(lot["ticker"], []).append(lot)

    for ticker, ticker_lots in by_ticker.items():
        current_price = price_map.get(ticker)
        if current_price is None or current_price <= 0:
            continue

        worst_loss = 0.0
        worst_lot: dict | None = None

        for lot in ticker_lots:
            try:
                purchase = datetime.date.fromisoformat(lot["purchase_date"])
            except (ValueError, TypeError):
                continue
            days_held = (today - purchase).days

            if not lot.get("cost_per_share"):
                continue  # missing basis, skip

            loss = (current_price - lot["cost_per_share"]) * lot["shares"]
            if loss < worst_loss:
                worst_loss = loss
                lot_type = "LT" if days_held >= 365 else "ST"
                worst_lot = {**lot, "_days_held": days_held, "_lot_type": lot_type}

        if worst_lot is None or worst_loss >= -TRIGGER_TAX_LOSS_MIN:
            continue

        unrealized_loss = worst_loss  # negative number
        shares = worst_lot["shares"]
        cost = worst_lot["cost_per_share"]
        lot_type = worst_lot["_lot_type"]

        # LT losses offset LT gains first (at LT rate); ST losses offset ST gains (at ST rate)
        benefit_rate = TAX_LT_RATE if lot_type == "LT" else TAX_ST_RATE
        tlh_benefit = abs(unrealized_loss) * benefit_rate

        # Wash sale window: 30 days before and after potential sale date (today)
        ws_start = (today - datetime.timedelta(days=30)).isoformat()
        ws_end = (today + datetime.timedelta(days=30)).isoformat()

        narrative = _llm_harvest_narrative(
            ticker=ticker,
            unrealized_loss=unrealized_loss,
            shares=shares,
            current_price=current_price,
            cost_basis=cost,
            ytd_st_gains=ytd_st_gains,
            tlh_benefit=tlh_benefit,
            wash_sale_start=ws_start,
            wash_sale_end=ws_end,
            lot_type=lot_type,
        )

        loss_label = f"unrealized {lot_type} loss"
        score = min(85, 50 + int(tlh_benefit / 100))
        recs.append(Recommendation(
            ticker=ticker,
            action="HARVEST",
            recommendation_score=score,
            confidence=80,
            priority="normal",
            why_now=(
                f"{loss_label.capitalize()} of ${abs(unrealized_loss):,.0f} can offset "
                f"${ytd_st_gains:,.0f} YTD gains — estimated tax savings: ${tlh_benefit:,.0f} "
                f"(at {benefit_rate:.0%} {lot_type} rate)."
            ),
            rationale=narrative["summary"],
            counter_case=narrative["action_risk"],
            no_action_case=narrative["no_action_case"],
            action_payload={
                "lot_id": worst_lot["id"],
                "purchase_date": worst_lot["purchase_date"],
                "days_held": worst_lot["_days_held"],
                "lot_type": lot_type,
                "shares": shares,
                "cost_per_share": cost,
                "current_price": current_price,
                "unrealized_loss": round(unrealized_loss, 2),
                "ytd_st_gains": round(ytd_st_gains, 2),
                "tlh_benefit": round(tlh_benefit, 2),
                "benefit_rate": benefit_rate,
                "st_tax_rate": TAX_ST_RATE,
                "lt_tax_rate": TAX_LT_RATE,
                "wash_sale_window_start": ws_start,
                "wash_sale_window_end": ws_end,
            },
            # If price recovers 4% the loss shrinks enough to re-evaluate
            dependencies=[{
                "dependency_type": "PRICE",
                "dependency_key": ticker,
                "original_value": current_price,
                "tolerance": 0.04,
                "invalidating_event": "PRICE_THRESHOLD",
            }],
        ))

    return recs


# ── Entry point ───────────────────────────────────────────────────────────────

def run_tax_agent(ctx: AgentContext) -> list[Recommendation]:
    all_lots = _load_all_lots()
    if not all_lots:
        return []

    price_map = {h.ticker: h.current_price for h in ctx.snapshot.holdings}
    today = datetime.date.today()
    year = str(today.year)
    ytd_st_gains = _ytd_st_gains(year)

    recs: list[Recommendation] = []
    recs.extend(_check_lt_crossover(all_lots, price_map, today))
    recs.extend(_check_tlh(all_lots, price_map, today, ytd_st_gains))
    return recs


register_agent("tax", run_tax_agent)
