#!/usr/bin/env python3
"""
Portfolio AI analysis engine.
Generates daily macro-aware portfolio insights and per-holding macro risk scores.
All AI calls go through ollama_client (phi-4-4bit on MLX).
"""
import csv
import json
import os
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from strategy_config import (
    LAYER_NAMES, LAYER_LABELS, LAYER_TARGETS, LAYER_DESCRIPTIONS, DRIFT_THRESHOLD,
)


def _normalize_ticker(t: str) -> str:
    """Mirror generate_dashboard.normalize_ticker: BRK.B → BRK-B."""
    t = str(t).strip().upper()
    if "." in t:
        left, right = t.split(".", 1)
        if right in {"A", "B", "C", "D"}:
            return f"{left}-{right}"
    return t


# ── Legislative connection rule ────────────────────────────────────────────────
# Single source of truth — injected verbatim into every AI prompt that involves
# legislative risk/opportunity assessment. Enforces a one-step direct connection:
# the bill must target this company's actual industry, products, or supply chain.
_LEG_RULE = (
    "LEGISLATIVE CONNECTION RULE (applies to all leg_risk, leg_opp, tax_angle, and "
    "legislative_watch fields): A bill qualifies ONLY if the connection is one direct "
    "logical step — the bill explicitly regulates, taxes, subsidizes, or creates demand "
    "for THIS company's actual business. Test: 'bill targets X → this company does X.' "
    "If the connection requires inference or analogy (e.g. a healthcare bill affecting a "
    "streaming company; an energy bill affecting a retailer; a defense bill affecting a "
    "consumer brand), it does NOT qualify — omit the field entirely or write null. "
    "Do not manufacture connections to fill the field. "
    "DOMAIN CROSS-CHECK: Each bill in the BILLS UNDER REVIEW section is annotated with "
    "[domains: ...]. Each ticker in the TICKER PROFILES section lists its domains. "
    "If a bill's domains and a ticker's domains share NO overlap, there is no direct "
    "connection — skip that bill for that ticker and write null."
)


def _extract_json(text: str):
    """
    Robustly extract the first complete JSON object from raw LLM output.
    Handles code fences (```json...```) and preamble text before the JSON.
    Tries each '{' position in order until one yields valid JSON.
    Returns the parsed object, or None if nothing parses.
    """
    import re
    # Strip common code-fence wrappers
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text.strip())
    dec = json.JSONDecoder()
    for i, ch in enumerate(text):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(text, i)
                return obj
            except (ValueError, json.JSONDecodeError):
                continue
    return None


def _is_placeholder_json(obj: dict) -> bool:
    """Return True if all string values in obj are '...' (reasoning sketch, not real output)."""
    vals = []
    for v in obj.values():
        if isinstance(v, str):
            vals.append(v.strip())
        elif isinstance(v, list) and v:
            vals.extend(str(x).strip() for x in v[:3])
    return bool(vals) and all(v == "..." for v in vals)


def _extract_last_json(text: str, required_keys=None):
    """Return the LAST valid JSON object in text that contains all required_keys
    and does not consist entirely of '...' placeholder values.

    Qwen3 thinking models write JSON sketches with '...' placeholders early in
    their reasoning chain, then write the real filled-in answer later. Scanning
    from the end (keeping the last match) picks up the real answer and ignores
    the reasoning drafts. required_keys filters out nested objects inside the
    answer (e.g. array elements) that don't have the top-level schema keys.
    """
    import re
    text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
    text = re.sub(r"\n?```\s*$", "", text.strip())
    dec = json.JSONDecoder()
    last_obj = None
    for i, ch in enumerate(text):
        if ch != "{":
            continue
        try:
            obj, _ = dec.raw_decode(text, i)
            if not isinstance(obj, dict):
                continue
            if required_keys and not all(k in obj for k in required_keys):
                continue
            if _is_placeholder_json(obj):
                continue
            last_obj = obj
        except (ValueError, json.JSONDecodeError):
            continue
    return last_obj

# Load .env before ollama_client reads LLM_URL at import time
_PROJECT_DIR_EARLY = Path(__file__).resolve().parent
try:
    from dotenv import load_dotenv as _load_dotenv
    _load_dotenv(_PROJECT_DIR_EARLY / ".env")
except Exception:
    pass

import ollama_client

PROJECT_DIR = Path(__file__).resolve().parent
DB_PATH = PROJECT_DIR / "out" / "investment.db"

_LAYER_NAMES_LONG = {
    n: f"{LAYER_NAMES[n]} ({LAYER_DESCRIPTIONS[n]})"
    for n in LAYER_NAMES
}

# ── Canonical macro framework ─────────────────────────────────────────────────
# Single source of truth for all three scoring systems: macro scores, news
# analysis, and portfolio insight. All prompts derive language from here.
MACRO_DIMS = {
    "rate_sensitivity": {
        "label":      "Rate Sensitivity",
        "short":      "Hurt by rising rates",
        "direction":  "risk",
        "prompt_def": (
            "How much does a +50bps rise in the 10Y Treasury yield hurt this position? "
            "(10=very hurt: long-duration bonds, high-PE growth, REITs, leveraged balance sheets; "
            "1=immune or benefits: short-duration cash, banks, financials with floating-rate assets)"
        ),
    },
    "inflation_hedge": {
        "label":      "Inflation Hedge",
        "short":      "Benefits from sustained inflation",
        "direction":  "benefit",
        "prompt_def": (
            "How well does this position benefit from sustained inflation above 3%? "
            "(10=strong hedge: gold, commodities, energy, TIPS, real assets, pricing-power franchises; "
            "1=hurt: fixed income, long-duration, consumer discretionary with margin pressure)"
        ),
    },
    "dollar_sensitivity": {
        "label":      "Dollar Sensitivity",
        "short":      "Hurt by strong dollar",
        "direction":  "risk",
        "prompt_def": (
            "How much does a strengthening US dollar hurt this position? "
            "(10=very hurt: multinational exporters with large overseas revenue, EM exposure, "
            "USD-priced commodity producers; 1=immune or benefits: domestic services, US importers)"
        ),
    },
    "geopolitical_risk": {
        "label":      "Geopolitical / Trade Risk",
        "short":      "Trade/geopolitical exposure",
        "direction":  "risk",
        "prompt_def": (
            "How exposed is this position to trade wars, tariffs, sanctions, or geopolitical disruption? "
            "(10=high: China-exposed tech, global supply chains, defense-adjacent, foreign revenue dependent; "
            "1=low: domestic utilities, US healthcare services, domestically sourced businesses)"
        ),
    },
}
SCORE_STALE_DAYS = 5          # scores older than this get a staleness warning in prompts
SCORE_DIMS   = list(MACRO_DIMS.keys())                      # backwards compat
SCORE_LABELS = {k: v["short"] for k, v in MACRO_DIMS.items()}  # backwards compat

# ── Holding profiles ─────────────────────────────────────────────────────────
# Per-ticker description and legislative domain list.  Used to cross-check bill
# domains against holding domains before the model writes leg_risk/leg_opp/tax_angle.
# Funds (is_fund=True) are passive vehicles — only connect to tax_capital_gains /
# tax_corporate; they have no direct operational regulatory exposure.
HOLDING_PROFILES = {
    # Layer 1 — Structural Ballast
    "VTSAX":  {"desc": "Vanguard Total Stock Market Index Fund (passive broad market)",  "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    "VFIAX":  {"desc": "Vanguard 500 Index Fund (passive S&P 500)",                      "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    "VTMGX":  {"desc": "Vanguard Developed Markets Index Fund (passive international)",  "domains": ["tax_capital_gains", "trade"],         "is_fund": True},
    "BRK-B":  {"desc": "Berkshire Hathaway — diversified holding company: insurance, energy (BNSF/utilities), financial services, consumer brands",
               "domains": ["financial", "energy", "trade", "consumer", "tax_corporate", "environment"]},
    # Layer 2 — Cash-Flow Engines
    "SCHD":   {"desc": "Schwab U.S. Dividend Equity ETF (passive dividend-focused)",     "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    "BP":     {"desc": "BP — integrated oil & gas company, global energy operations",
               "domains": ["energy", "environment", "trade", "tax_corporate"]},
    # Layer 3 — Compounders
    "FSPTX":  {"desc": "Fidelity Select Technology Portfolio (active tech fund)",        "domains": ["technology", "tax_capital_gains"], "is_fund": True},
    "STZ":    {"desc": "Constellation Brands — beer, wine, and spirits producer; significant Mexico import operations",
               "domains": ["food_ag", "consumer", "trade", "tax_corporate"]},
    "SNA":    {"desc": "Snap-on Tools — industrial tools and equipment manufacturer",
               "domains": ["labor", "trade", "tax_corporate"]},
    "SLYV":   {"desc": "SPDR S&P 600 Small-Cap Value ETF (passive small-cap value)",    "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    "GRMN":   {"desc": "Garmin — GPS navigation, aviation avionics, wearables, marine electronics",
               "domains": ["technology", "aviation", "consumer", "trade"]},
    "EW":     {"desc": "Edwards Lifesciences — structural heart valves and hemodynamic monitoring (medical devices)",
               "domains": ["healthcare", "tax_corporate"]},
    "ITW":    {"desc": "Illinois Tool Works — diversified industrial manufacturer: automotive, construction, food equipment",
               "domains": ["trade", "labor", "environment", "tax_corporate"]},
    "NFLX":   {"desc": "Netflix — streaming entertainment subscription service",
               "domains": ["telecom", "technology", "consumer", "tax_corporate"]},
    "WMT":    {"desc": "Walmart — retail and grocery chain; large China import sourcing; major employer",
               "domains": ["consumer", "trade", "labor", "food_ag", "tax_corporate"]},
    # Layer 4 — Convexity / Optionality
    "JOBY":   {"desc": "Joby Aviation — electric air taxi (eVTOL) manufacturer, FAA certification in progress",
               "domains": ["aviation", "energy", "environment", "technology", "tax_corporate"]},
    "IGV":    {"desc": "iShares Expanded Tech-Software ETF (passive software-sector)",  "domains": ["technology", "tax_capital_gains"], "is_fund": True},
    "BTC":    {"desc": "Bitcoin — decentralized cryptocurrency",
               "domains": ["crypto", "financial", "tax_capital_gains"]},
    "DSGX":   {"desc": "Descartes Systems — logistics and supply chain software platform",
               "domains": ["technology", "transportation", "trade", "tax_corporate"]},
    "VVIAX":  {"desc": "Vanguard Value Index Fund Admiral (passive large-cap value index)", "domains": ["tax_capital_gains", "tax_corporate"], "is_fund": True},
    # Layer 5 — Shock Absorbers
    "ITOCF":  {"desc": "Itochu Corp — Japanese trading conglomerate: food, textiles, energy, finance",
               "domains": ["trade", "food_ag", "energy", "financial"]},
    "MITSF":  {"desc": "Mitsubishi Corp — Japanese conglomerate: energy, materials, finance, infrastructure",
               "domains": ["trade", "energy", "financial", "environment"]},
    "UNP":    {"desc": "Union Pacific — Class I freight railroad, major cross-country rail network",
               "domains": ["transportation", "trade", "labor", "environment", "tax_corporate"]},
    "MCO":    {"desc": "Moody's — credit rating agency and financial data/analytics provider",
               "domains": ["financial", "ratings_advisory", "tax_corporate"]},
    "NOC":    {"desc": "Northrop Grumman — defense contractor, aerospace and nuclear systems",
               "domains": ["defense", "aviation", "tax_corporate"]},
}


_TAX_CATCHALL = {"tax_corporate", "tax_capital_gains"}

def _bills_with_holdings(bills: list, tickers: list) -> str:
    """Format bills annotated with pre-computed portfolio matches.
    Each bill line shows exactly which holdings are directly affected.
    Bills marked 'No holdings affected' are irrelevant to this portfolio.

    Matching uses primary domains only (strips tax_corporate/tax_capital_gains
    when other domains exist) to prevent every budget bill from matching all stocks."""
    lines = ["BILLS UNDER REVIEW — OFFICIAL RECORD (Congress.gov):"]
    for b in bills[:12]:
        bill_domains = set(b.get("domains", []))
        id_str   = f"[{b.get('bill_id', '')}] " if b.get("bill_id") else ""
        stage    = f" — {b['stage']}" if b.get("stage") else ""
        domain_s = f" [domains: {', '.join(sorted(bill_domains))}]" if bill_domains else ""
        # Strip generic tax catch-all domains when primary domains exist
        primary = bill_domains - _TAX_CATCHALL
        match_against = primary if primary else bill_domains
        matched = []
        for t in tickers:
            p = HOLDING_PROFILES.get(t) or HOLDING_PROFILES.get(t.replace(".", "-"))
            if p and (match_against & set(p["domains"])):
                matched.append(t)
        match_s = f" → Portfolio match: {', '.join(matched)}" if matched else " → No holdings affected"
        lines.append(f"  {id_str}{b['title']}{domain_s}{stage}{match_s}")
        if b.get("summary") and matched:
            lines.append(f"    CRS: {b['summary'][:200]}")
    return "\n".join(lines)


def _holding_profile_block(tickers: list) -> str:
    """Format a TICKER PROFILES section for AI prompts listing each ticker's desc and domains."""
    lines = ["TICKER PROFILES (use domains to evaluate legislative relevance):"]
    for t in tickers:
        profile = HOLDING_PROFILES.get(t) or HOLDING_PROFILES.get(t.replace(".", "-"))
        if profile:
            domain_str = ", ".join(profile["domains"])
            fund_note  = " (passive fund — only tax/budget bills apply)" if profile.get("is_fund") else ""
            lines.append(f"  {t}: {profile['desc']}{fund_note} [domains: {domain_str}]")
        else:
            lines.append(f"  {t}: (no profile — evaluate on company fundamentals)")
    return "\n".join(lines)


# ── DB helpers ────────────────────────────────────────────────────────────────

def _init_ai_tables():
    if not DB_PATH.exists():
        return
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("""CREATE TABLE IF NOT EXISTS ai_insights (
        day          TEXT PRIMARY KEY,
        insight      TEXT,
        macro_snap   TEXT,
        generated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS holding_macro_scores (
        ticker     TEXT PRIMARY KEY,
        scores     TEXT,
        updated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS news_summaries (
        day          TEXT PRIMARY KEY,
        summaries    TEXT,
        generated_at TEXT
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS holding_macro_scores_history (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker    TEXT NOT NULL,
        scores    TEXT NOT NULL,
        scored_at TEXT NOT NULL
    )""")
    conn.execute("""CREATE TABLE IF NOT EXISTS macro_score_summaries (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        summary_json TEXT NOT NULL,
        created_at   TEXT NOT NULL
    )""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_hmsh_ticker_scored "
        "ON holding_macro_scores_history (ticker, scored_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_mss_created "
        "ON macro_score_summaries (created_at DESC)"
    )
    conn.commit()
    conn.close()


def _score_val(dim_data):
    """Extract integer score from {score, reason} dict or bare int. Returns int or None."""
    if isinstance(dim_data, dict):
        v = dim_data.get("score")
    elif isinstance(dim_data, (int, float)):
        v = dim_data
    else:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _score_reason(dim_data) -> str:
    if isinstance(dim_data, dict):
        return str(dim_data.get("reason", ""))
    return ""


def _get_macro_scores_block(tickers=None, compact=False, reason_max=120):
    """
    Load macro scores from DB and return (scores_dict, formatted_block_for_prompt).
    Scores older than SCORE_STALE_DAYS get a staleness annotation.
    tickers: if given, only include those tickers in the block.
    compact: if True, omit per-dimension reasons (much smaller output, use for news prompts).
    reason_max: max chars per reason line when compact=False.
    """
    if not DB_PATH.exists():
        return {}, ""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, scores, updated_at FROM holding_macro_scores"
        ).fetchall()
        conn.close()
    except Exception:
        return {}, ""

    stale_cutoff = (datetime.now() - timedelta(days=SCORE_STALE_DAYS)).strftime("%Y-%m-%d")
    scores: dict = {}
    for r in rows:
        t = _normalize_ticker(r["ticker"])
        if tickers and t not in tickers:
            continue
        try:
            data = json.loads(r["scores"])
            scored_at = (r["updated_at"] or "")[:10]
            data["_scored_at"] = scored_at
            data["_stale"]     = scored_at < stale_cutoff
            scores[t] = data
        except Exception:
            pass

    if not scores:
        return {}, ""

    lines = [
        "PORTFOLIO MACRO DIMENSION SCORES (weekly AI scoring; 50bps rate-move basis; 1=low risk, 10=high):",
        "  Dimensions: Rate Sensitivity | Inflation Hedge | Dollar Sensitivity | Geopolitical/Trade Risk",
    ]
    for t, data in scores.items():
        scored_at = data["_scored_at"]
        stale_note = (f"  ⚠ scored {scored_at}" if data["_stale"] else f"  scored {scored_at}")
        row = "  ".join(
            f"{dim[:4]}={_score_val(data.get(dim)) or '?'}"
            for dim in SCORE_DIMS
        )
        lines.append(f"  {t} [{row}]{stale_note}")
        if not compact:
            for dim in SCORE_DIMS:
                sv = _score_val(data.get(dim))
                sr = _score_reason(data.get(dim))
                if sv is not None and sr:
                    sr_trunc = sr[:reason_max] + "…" if len(sr) > reason_max else sr
                    lines.append(f"    {MACRO_DIMS[dim]['short']}: {sv}/10 — {sr_trunc}")
    return scores, "\n".join(lines)


def _load_holdings_csv() -> list[dict]:
    path = PROJECT_DIR / "holdings.csv"
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _get_layer_weights_from_db() -> dict:
    """Return most recent layer_day row as {layer_label: weight_pct}."""
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    day = conn.execute("SELECT MAX(day) FROM layer_day").fetchone()[0]
    if not day:
        conn.close()
        return {}
    rows = conn.execute("SELECT * FROM layer_day WHERE day=?", (day,)).fetchall()
    conn.close()
    return {r["layer"]: {"weight_pct": r["weight_pct"], "chg_pct": r["change_pct"],
                         "value": r["value"]} for r in rows}


def _get_holding_prices_from_db() -> dict:
    """Return most recent holding_day rows as {ticker: {price, chg_pct, value, weight_pct}}."""
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    day = conn.execute("SELECT MAX(day) FROM holding_day").fetchone()[0]
    if not day:
        conn.close()
        return {}
    rows = conn.execute("SELECT * FROM holding_day WHERE day=?", (day,)).fetchall()
    conn.close()
    return {r["ticker"]: dict(r) for r in rows}


def _get_drift_alerts(layer_weights: dict) -> list[dict]:
    """Return layers with drift >= 5pp from targets."""
    _targets_by_label = {LAYER_LABELS[n]: LAYER_TARGETS[n] for n in LAYER_TARGETS}
    alerts = []
    for layer_label, data in layer_weights.items():
        target = _targets_by_label.get(layer_label)
        if target is None:
            continue
        drift = data["weight_pct"] - target
        if abs(drift) >= DRIFT_THRESHOLD:
            alerts.append({
                "layer": layer_label,
                "current": round(data["weight_pct"], 1),
                "target": target,
                "drift": round(drift, 1),
            })
    return sorted(alerts, key=lambda x: abs(x["drift"]), reverse=True)


def _get_upcoming_events() -> list[dict]:
    """Return earnings / ex-div events from DB within the next 7 days (if stored)."""
    return []


# ── Personal context builders ─────────────────────────────────────────────────

def _get_cc_context() -> str:
    """Build covered call program summary for prompt injection."""
    if not DB_PATH.exists():
        return ""
    today = date.today()

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM cc_positions ORDER BY opened_date DESC").fetchall()
    conn.close()

    if not rows:
        return ""

    open_pos   = [r for r in rows if r["status"] == "open"]
    closed_pos = [r for r in rows if r["status"] != "open"]
    cc_tickers = sorted(set(r["ticker"] for r in rows))

    lines = ["COVERED CALL PROGRAM:"]
    lines.append(f"All-time CC tickers: {', '.join(cc_tickers)}")

    if open_pos:
        lines.append(f"\nOpen CC positions ({len(open_pos)}):")
        for r in open_pos:
            exp_date = date.fromisoformat(r["expiry"])
            dte = (exp_date - today).days
            gross = r["premium_per_contract"] * r["contracts"] * 100
            dte_str = (f"{dte} DTE" if dte >= 0
                       else f"exp {abs(dte)} days ago — needs status update")
            mark = r["current_mark"]
            mark_str = f", mark ${mark:.3f}" if mark is not None else ""
            lines.append(
                f"  {r['ticker']:6s} ${r['strike']:.2f} strike, exp {r['expiry']} "
                f"({dte_str}), ${r['premium_per_contract']:.3f}/contract × "
                f"{r['contracts']}c = ${gross:.0f} gross{mark_str}"
            )

    if closed_pos:
        cutoff = (today - timedelta(days=90)).isoformat()
        recent = [r for r in closed_pos if (r["opened_date"] or "") >= cutoff]
        if recent:
            lines.append(f"\nClosed positions (last 90 days):")
            for r in recent:
                net = r["net_premium"] or r["premium_per_contract"] * r["contracts"] * 100
                ctype = (r["close_type"] or "closed").upper()
                lines.append(
                    f"  {r['ticker']:6s} ${r['strike']:.2f} strike, exp {r['expiry']}, "
                    f"{ctype} — collected ${net:.0f}"
                )

    total_open  = sum(r["premium_per_contract"] * r["contracts"] * 100 for r in open_pos)
    total_closed = sum(r["net_premium"] or 0 for r in closed_pos)
    lines.append(f"\nCC income: ${total_open:.0f} gross in open positions, ${total_closed:.0f} from closed (all-time in DB)")
    return "\n".join(lines)


def _get_lot_context() -> str:
    """Build cost basis, holding periods, and unrealized P&L for prompt injection."""
    if not DB_PATH.exists():
        return ""
    today = date.today()

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    # Per-ticker aggregates from cost_lots
    summary = conn.execute("""
        SELECT ticker,
               COUNT(*)                                    AS lots,
               SUM(shares)                                 AS total_shares,
               SUM(shares * cost_per_share) / SUM(shares) AS avg_cost,
               MIN(purchase_date)                          AS oldest,
               MAX(purchase_date)                          AS newest
        FROM cost_lots
        GROUP BY ticker
        ORDER BY lots DESC
    """).fetchall()

    # Current prices
    latest_day = conn.execute("SELECT MAX(day) FROM holding_day").fetchone()[0]
    prices: dict = {}
    if latest_day:
        for r in conn.execute("SELECT ticker, price FROM holding_day WHERE day=?", (latest_day,)):
            prices[r["ticker"]] = r["price"]
    conn.close()

    if not summary:
        return ""

    lines = ["COST BASIS & HOLDING PERIODS (tax lot analysis):"]

    # Systematic accumulators
    accumulators = [(r, r["lots"]) for r in summary if r["lots"] >= 10]
    if accumulators:
        lines.append("\nSystematic accumulators (10+ lots — DCA/DRIP pattern):")
        for r, _ in accumulators:
            oldest_date = date.fromisoformat(r["oldest"])
            age_mo = (today - oldest_date).days // 30
            lt_date = oldest_date + timedelta(days=365)
            lt_note = ("all lots LT eligible" if (today - oldest_date).days >= 365
                       else f"oldest lot LT on {lt_date}")
            lines.append(
                f"  {r['ticker']}: {r['lots']} lots, {r['total_shares']:.0f} shares, "
                f"oldest {r['oldest']} ({age_mo}mo old), {lt_note}"
            )

    # Unrealized P&L for all tickers with prices
    lines.append("\nUnrealized gain/loss by position (avg cost → current price):")
    rows_with_prices = [
        r for r in summary if prices.get(r["ticker"]) is not None
    ]
    rows_with_prices.sort(key=lambda r: (prices[r["ticker"]] - r["avg_cost"]) / r["avg_cost"], reverse=True)
    for r in rows_with_prices:
        curr = prices[r["ticker"]]
        pct  = (curr - r["avg_cost"]) / r["avg_cost"] * 100
        oldest_date = date.fromisoformat(r["oldest"])
        lt_label = "LT" if (today - oldest_date).days >= 365 else "ST"
        tlh_flag = " ← TLH candidate" if pct < -5 else ""
        sign = "+" if pct >= 0 else ""
        lines.append(
            f"  {r['ticker']:6s} {sign}{pct:.0f}% unrealized "
            f"(avg ${r['avg_cost']:.2f} → ${curr:.2f}), "
            f"{r['total_shares']:.0f} shares, oldest lot {r['oldest']} ({lt_label}){tlh_flag}"
        )

    # Positions crossing LT threshold in next 90 days
    approaching = []
    for r in summary:
        oldest_date = date.fromisoformat(r["oldest"])
        lt_date = oldest_date + timedelta(days=365)
        days_to_lt = (lt_date - today).days
        if 0 < days_to_lt <= 90:
            approaching.append((r["ticker"], r["oldest"], lt_date, days_to_lt))
    if approaching:
        approaching.sort(key=lambda x: x[3])
        lines.append("\nPositions crossing LT threshold in next 90 days:")
        for ticker, oldest, lt_date, days in approaching:
            lines.append(f"  {ticker}: oldest lot {oldest} → LT on {lt_date} ({days} days away)")

    return "\n".join(lines)


def _get_realized_context() -> str:
    """Summarize YTD realized gains from sell_transactions."""
    if not DB_PATH.exists():
        return ""
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        count = conn.execute("SELECT COUNT(*) FROM sell_transactions").fetchone()[0]
        if count == 0:
            conn.close()
            return "REALIZED GAINS YTD:\n  No sell transactions recorded — all gains/losses are currently unrealized."
        year = str(date.today().year)
        rows = conn.execute(
            "SELECT * FROM sell_transactions WHERE strftime('%Y', sell_date) = ?", (year,)
        ).fetchall()
        conn.close()
    except Exception:
        return ""

    if not rows:
        return f"REALIZED GAINS YTD ({year}):\n  No sales this year."

    st_total = sum(r["st_gain"] or 0 for r in rows)
    lt_total = sum(r["lt_gain"] or 0 for r in rows)
    lines = [f"REALIZED GAINS YTD ({year}):"]
    lines.append(f"  Short-term: ${st_total:+,.0f}")
    lines.append(f"  Long-term:  ${lt_total:+,.0f}")
    lines.append(f"  Total:      ${st_total + lt_total:+,.0f}")
    return "\n".join(lines)


def _get_behavior_patterns() -> str:
    """Derive investor behavior patterns from CC and lot data."""
    if not DB_PATH.exists():
        return ""

    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row

    cc_rows = conn.execute("SELECT ticker, status FROM cc_positions").fetchall()
    lot_counts = conn.execute(
        "SELECT ticker, COUNT(*) as cnt, SUM(shares) as total FROM cost_lots GROUP BY ticker"
    ).fetchall()
    conn.close()

    cc_tickers   = sorted(set(r["ticker"] for r in cc_rows))
    open_cc      = sorted(set(r["ticker"] for r in cc_rows if r["status"] == "open"))
    expired_ok   = sorted(set(r["ticker"] for r in cc_rows if r["status"] == "expired"))
    lot_dict     = {r["ticker"]: r["total"] for r in lot_counts}
    accumulators = [(r["ticker"], r["cnt"], r["total"]) for r in lot_counts if r["cnt"] >= 10]
    accumulators.sort(key=lambda x: x[1], reverse=True)

    lines = ["OBSERVED INVESTOR BEHAVIOR PATTERNS:"]

    if accumulators:
        acc_str = ", ".join(f"{t} ({n} lots, {s:.0f} sh)" for t, n, s in accumulators)
        lines.append(f"- Systematic DCA/accumulator: {acc_str}")

    if cc_tickers:
        lines.append(f"- Active CC writer on: {', '.join(cc_tickers)}")
    if open_cc:
        lines.append(f"  Currently open calls: {', '.join(open_cc)}")
    if expired_ok:
        lines.append(f"  Expired worthless (favorable outcomes): {', '.join(set(expired_ok))}")

    # Large holdings not in CC program (100+ shares)
    non_cc_large = [(t, s) for t, s in lot_dict.items() if t not in cc_tickers and s >= 100]
    non_cc_large.sort(key=lambda x: x[1], reverse=True)
    if non_cc_large:
        nc_str = ", ".join(f"{t} ({s:.0f} sh)" for t, s in non_cc_large)
        lines.append(f"- CC expansion candidates (100+ shares, no active calls): {nc_str}")

    return "\n".join(lines)


# ── Prompt builders ───────────────────────────────────────────────────────────

def _get_news_block(holdings: list[dict], max_per_ticker: int = 3) -> str:
    """Fetch holding-specific news headlines and return a prompt block."""
    tickers = [str(h.get("Stock", "")).strip().upper() for h in holdings if h.get("Stock")]
    tickers = list(dict.fromkeys(t for t in tickers if t))
    if not tickers:
        return ""
    try:
        import news_fetcher
        result = news_fetcher.fetch(tickers)
        by_ticker = result.get("by_ticker", {})
        if not by_ticker:
            return ""
        lines = ["RECENT NEWS FOR YOUR HOLDINGS (from WSJ, Barrons, MarketWatch, Yahoo Finance):"]
        for ticker in tickers:
            items = by_ticker.get(ticker, [])[:max_per_ticker]
            if not items:
                continue
            lines.append(f"  {ticker}:")
            for item in items:
                src = item.get("source", "")
                title = item.get("title", "")
                lines.append(f"    - [{src}] {title}")
        return "\n".join(lines) + "\n"
    except Exception as e:
        print(f"[AI] News fetch for prompt failed: {e}")
        return ""


def _build_thesis_health_block(holdings: list[dict]) -> str:
    """Summarise active thesis health for all holdings that have evaluated pillars."""
    try:
        import agent_db as _adb
        lines: list[str] = []
        for h in holdings:
            ticker = str(h.get("Stock", "")).strip().upper()
            if not ticker:
                continue
            t = _adb.get_thesis(ticker)
            if not t or t.get("status") != "ACTIVE":
                continue
            pillars = t.get("pillars", [])
            scored = [p for p in pillars if p.get("score") is not None]
            if not scored:
                continue
            health = t.get("health_score")
            violated = [p["name"] for p in pillars if p.get("status") == "VIOLATED"]
            warning  = [p["name"] for p in pillars if p.get("status") == "WARNING"]
            line = f"  {ticker}: health={health:.0f}/100" if health is not None else f"  {ticker}: health=?"
            if violated:
                line += f"  VIOLATED=[{', '.join(violated)}]"
            if warning:
                line += f"  WARNING=[{', '.join(warning)}]"
            lines.append(line)
        if not lines:
            return ""
        return (
            "INVESTMENT THESIS HEALTH (from thesis monitor agent — flag violations in risk_flags):\n"
            + "\n".join(lines) + "\n"
        )
    except Exception:
        return ""


def _build_portfolio_block(holdings: list[dict], prices: dict) -> str:
    lines = ["PORTFOLIO HOLDINGS:"]
    lines.append(f"{'Ticker':<8} {'Layer':<6} {'Value':>10} {'Day%':>7} {'Wt%':>6}")
    lines.append("-" * 45)
    for h in sorted(holdings, key=lambda x: int(x.get("Layer", 5))):
        t = str(h.get("Stock", "")).strip().upper()
        layer = h.get("Layer", "?")
        p = prices.get(t, {})
        value = p.get("value", 0) or 0
        chg   = p.get("change_pct", 0) or 0
        wt    = p.get("weight_pct", 0) or 0
        lines.append(f"{t:<8} L{layer:<5} ${value:>9,.0f} {chg:>+6.1f}% {wt:>5.1f}%")
    return "\n".join(lines)


def _build_layer_block(layer_weights: dict, drift_alerts: list[dict]) -> str:
    lines = ["LAYER WEIGHTS vs TARGETS:"]
    for label, data in sorted(layer_weights.items()):
        wt  = data.get("weight_pct", 0)
        chg = data.get("chg_pct", 0)
        lines.append(f"  {label}: {wt:.1f}% actual ({chg:+.1f}% today)")
    if drift_alerts:
        lines.append("\nDRIFT ALERTS (≥5pp from target):")
        for d in drift_alerts:
            lines.append(f"  {d['layer']}: {d['current']:.1f}% vs {d['target']:.0f}% target ({d['drift']:+.1f}pp)")
    return "\n".join(lines)


# ── Daily insight ─────────────────────────────────────────────────────────────

def get_cached_insight_today():
    """Return (insight_dict, generated_at_str) for today, or (None, None)."""
    _init_ai_tables()
    today = date.today().isoformat()
    if not DB_PATH.exists():
        return None, None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        row = conn.execute(
            "SELECT insight, generated_at FROM ai_insights WHERE day=?", (today,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0]), (row[1] or "")
    except Exception:
        pass
    return None, None


def get_cached_news_summaries_today():
    """Return (data, generated_at_str) for today's cached per-ticker news summaries, or (None, None).
    Returns (sentinel, generated_at) during error cooldown so caller can distinguish."""
    _init_ai_tables()
    today = date.today().isoformat()
    if not DB_PATH.exists():
        return None, None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        row = conn.execute(
            "SELECT summaries, generated_at FROM news_summaries WHERE day=?", (today,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            data = json.loads(row[0])
            generated_at = row[1] or ""
            if data.get("_failed"):
                # Allow retry after 30-minute cooldown
                try:
                    gen_ts = datetime.strptime(generated_at, "%Y-%m-%d %H:%M:%S")
                    if (datetime.now() - gen_ts).total_seconds() < 1800:
                        return data, generated_at  # still in cooldown — block retry
                except Exception:
                    pass
                return None, None  # cooldown expired — allow fresh attempt
            return data, generated_at
    except Exception:
        pass
    return None, None


def generate_news_summaries(force: bool = False) -> dict:
    """
    For each holding that has recent news, generate an AI summary of the
    headlines plus a macro-angle sentence.  Returns {ticker: {summary, macro_angle}}.
    Cached in DB by day.
    """
    _init_ai_tables()
    today = date.today().isoformat()

    if not force:
        cached, _ = get_cached_news_summaries_today()
        if cached is not None:
            sample = next((v for v in cached.values() if isinstance(v, dict)), {})
            # Accept cache only if it has current schema: per-ticker news + portfolio _outlook
            if sample.get("news") and isinstance(cached.get("_outlook"), dict):
                return cached

    if not ollama_client.available():
        return {"error": "AI model unavailable — check MLX server"}

    holdings = _load_holdings_csv()
    tickers = [str(h.get("Stock", "")).strip().upper() for h in holdings if h.get("Stock")]
    tickers = list(dict.fromkeys(t for t in tickers if t))

    import news_fetcher
    result = news_fetcher.fetch(tickers)
    by_ticker = result.get("by_ticker", {})
    tickers_with_news = {t: items for t, items in by_ticker.items() if items}
    if not tickers_with_news:
        return {}

    news_fetcher.enrich_with_bodies(tickers_with_news)

    import macro_context
    macro = macro_context.fetch()
    macro_block = macro.get("formatted_block", "Macro data unavailable.")

    # Load macro scores for newsworthy tickers — compact (no per-dim reasons) to stay within context budget
    news_tickers = list(tickers_with_news.keys())
    _, scores_block = _get_macro_scores_block(tickers=news_tickers, compact=True)

    # Keep news content lean to stay within 8192-token context window
    news_block = ""
    for ticker, items in tickers_with_news.items():
        news_block += f"\n{ticker}:\n"
        for item in items[:4]:
            src     = item.get("source", "")
            title   = item.get("title", "")
            body    = item.get("body", "")
            excerpt = item.get("excerpt", "")
            news_block += f"  [{src}] {title}\n"
            detail = body[:150] if body else excerpt[:100] if excerpt else ""
            if detail:
                news_block += f"    {detail}\n"

    fed   = macro.get("fed_funds", "N/A")
    tnx   = macro.get("yield_10y", "N/A")
    cpi   = macro.get("cpi_yoy", "N/A")
    unemp = macro.get("unemployment", "N/A")
    vix   = macro.get("vix", "N/A")
    dol   = macro.get("dollar_interp", "N/A")
    crv   = macro.get("curve_interp", "N/A")

    official_bills = macro.get("official_bills", [])
    media_coverage = macro.get("legislative_media", [])

    if official_bills:
        off_lines = []
        for b in official_bills[:12]:
            id_str   = f"[{b.get('bill_id', '')}] " if b.get("bill_id") else ""
            stage    = f" — Stage: {b['stage']}" if b.get("stage") else ""
            dt       = (b.get("action_date") or b.get("introduced") or "")[:10]
            date_s   = f" ({dt})" if dt else ""
            domain_s = f" [domains: {', '.join(b['domains'])}]" if b.get("domains") else ""
            off_lines.append(f"  {id_str}{b['title']}{domain_s}{stage}{date_s}")
            if b.get("summary"):
                off_lines.append(f"    CRS Summary: {b['summary'][:350]}")
            if b.get("latest_action") and b.get("stage") in (
                "Floor vote", "Passed chamber", "Signed into law", "Vetoed"
            ):
                off_lines.append(f"    Latest action: {b['latest_action']}")
        official_block = "\n".join(off_lines)
    else:
        official_block = "  No official bill data available."

    all_portfolio_tickers = [str(h.get("Stock", "")).strip().upper() for h in holdings if h.get("Stock")]
    all_portfolio_tickers = list(dict.fromkeys(t for t in all_portfolio_tickers if t))
    profiles_block = _holding_profile_block(list(tickers_with_news.keys()))
    bills_holdings_block = _bills_with_holdings(official_bills, all_portfolio_tickers)

    media_block = (
        "\n".join(f"  - {b['title']}" for b in media_coverage[:6])
        if media_coverage else "  None."
    )

    legislative_block = official_block  # kept for outlook_prompt

    prompt = f"""You are a portfolio risk analyst helping a personal investor take action. Your job is not to describe — it is to FLAG risks, surface OPPORTUNITIES, and call out TAX implications so the investor knows what needs attention TODAY.

CURRENT MACRO ENVIRONMENT:
{macro_block}

KEY NUMBERS:
  Fed Funds Rate: {fed}%  |  10Y Treasury: {tnx}%  |  CPI YoY: {cpi}%
  Unemployment: {unemp}%  |  VIX: {vix}  |  Dollar: {dol}  |  Yield Curve: {crv}

{scores_block}

RECENT NEWS BY HOLDING (last 24 hours):
{news_block}

BILLS UNDER REVIEW — OFFICIAL GOVERNMENT RECORD (Congress.gov; authoritative — weight these facts over any media framing):
{official_block}

LEGISLATIVE MEDIA COVERAGE (secondary; editorial sources may reflect political bias — use only to identify story angles, not as factual basis):
{media_block}

For each ticker in the news above, provide these components:

1. "news" — 2-3 sentences on what actually happened. Reference specific numbers, events, or company actions. No vague summaries.
2. "rates" — CONDITIONAL: only include if MACRO SCORES rate_sensitivity is 7 or higher AND the current rate level creates a concrete near-term risk (e.g., refinancing pressure, spread widening, valuation compression on a high-multiple stock). A low score means the company is rate-insensitive — do not fill this field just to explain immunity. Omit entirely for scores 1-6 unless today's news changes the picture.
3. "trade" — CONDITIONAL: only include if this company has direct material exposure to active tariff, FX, or trade policy changes in the current news cycle (e.g., specific China tariff hitting a core product line, dollar move affecting a major revenue stream). Omit if the company has minimal international/trade exposure or if nothing has changed.
4. "environment" — CONDITIONAL: only include if there is a material current headwind or tailwind that should affect a near-term decision (e.g., accelerating margin compression, cycle inflection, significant regulatory shift underway). Omit if macro conditions for this company are neutral or unchanged.
5. "leg_risk" — Apply the LEGISLATIVE CONNECTION RULE below. If a bill directly burdens this company's business (regulation, cost, pricing pressure), name it by ID, explain the mechanism, and give its stage. Otherwise omit.
6. "leg_opp" — Apply the LEGISLATIVE CONNECTION RULE below. If a bill directly benefits this company (subsidy, deregulation, new demand), name it by ID, explain the mechanism, and give its stage. Otherwise omit.
7. "tax_angle" — ONLY if a bill directly changes the tax treatment of this holding (capital gains rates, corporate tax, sector-specific credits). Name the bill by ID. Omit if not applicable.

{profiles_block}

{_LEG_RULE}

Also provide a top-level "_outlook" object (not per-ticker) with four keys:
- "top_risk": The single most urgent legislative or macro risk to the portfolio right now. One sentence, specific.
- "top_opportunity": The single clearest legislative or macro tailwind. One sentence, specific.
- "tax_watch": Any pending legislation that could affect the investor's tax bill on current positions (capital gains rates, wash-sale rules, SALT cap changes, corporate rates). If none, write null.
- "action_items": A JSON array of 2-4 specific, actionable things the investor should do or watch this week. Each item is one sentence starting with an action verb (Review, Consider, Watch, Monitor, Avoid).

Return ONLY valid JSON — no markdown, no extra text. START with "_outlook" before any tickers:
{{
  "_outlook": {{
    "top_risk": "...",
    "top_opportunity": "...",
    "tax_watch": "... or null",
    "action_items": ["...", "..."]
  }},
  "TICKER": {{
    "news": "...",
    "rates": "(omit if rate_sensitivity < 7 and no new rate catalyst)",
    "trade": "(omit if no material trade/FX exposure or development)",
    "environment": "(omit if macro conditions for this name are neutral)",
    "leg_risk": "(omit if not applicable)",
    "leg_opp": "(omit if not applicable)",
    "tax_angle": "(omit if not applicable)"
  }}
}}

Only include tickers with news. Only include leg_risk, leg_opp, tax_angle when specifically applicable. Be direct and use concrete numbers — vague analysis is not useful."""

    outlook_prompt = f"""You are a portfolio risk analyst. Given the context below, produce a concise portfolio-level action briefing in JSON.

MACRO: Fed={fed}%, 10Y={tnx}%, CPI={cpi}%, VIX={vix}, Dollar={dol}, Curve={crv}

{bills_holdings_block}

Each bill above is pre-annotated with "Portfolio match: TICKER" showing which holdings are directly affected. Bills marked "No holdings affected" are irrelevant to this portfolio — do not cite them.

Return ONLY this JSON object with exactly these four keys:
{{
  "top_risk": "<one sentence: the single most urgent macro or legislative risk — for legislation, only cite bills that show a Portfolio match above>",
  "top_opportunity": "<one sentence: the clearest macro or legislative tailwind — for legislation, only cite bills that show a Portfolio match above; name the specific matching ticker>",
  "tax_watch": "<one sentence: any pending tax legislation relevant to these holdings per the Portfolio match annotations, or null if none>",
  "action_items": ["<action verb + specific action>", "<action verb + specific action>", "<action verb + specific action>"]
}}

Be specific. Name the legislation by ID and the matching holding. No generic statements."""

    def _cache_sentinel(error_msg):
        now_s = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if DB_PATH.exists():
            try:
                c = sqlite3.connect(str(DB_PATH), timeout=10)
                c.execute(
                    "INSERT OR REPLACE INTO news_summaries (day, summaries, generated_at) VALUES (?,?,?)",
                    (today, json.dumps({"_failed": True, "_error": error_msg}), now_s)
                )
                c.commit()
                c.close()
            except Exception:
                pass

    # Call 1: per-ticker summaries
    full_text = ""
    try:
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.3, num_predict=6000
        ):
            full_text += tok
    except Exception as e:
        err = f"AI generation failed: {e}"
        _cache_sentinel(err)
        return {"error": err}

    summaries = _extract_json(full_text)
    if summaries is None:
        err = "AI returned malformed JSON"
        print(f"[NewsSummaries] Parse failed. Raw output (first 600): {full_text[:600]!r}")
        _cache_sentinel(err)
        return {"error": err, "raw": full_text[:500]}

    # Strip fields where the AI echoed the placeholder "omit" text instead of omitting the field
    _OMIT_FIELDS = {"rates", "trade", "environment", "leg_risk", "leg_opp", "tax_angle"}
    for ticker_data in summaries.values():
        if not isinstance(ticker_data, dict):
            continue
        for field in _OMIT_FIELDS:
            val = ticker_data.get(field)
            if isinstance(val, str) and (val.lower().startswith("omit") or val.lower().startswith("(omit")):
                del ticker_data[field]

    # Call 2: portfolio-level outlook
    try:
        outlook_raw = ""
        for tok in ollama_client.stream_generate(
            outlook_prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.2, num_predict=4000,
            enable_thinking=True
        ):
            outlook_raw += tok
        outlook_obj = _extract_last_json(outlook_raw, required_keys=["top_risk"])
        if outlook_obj:
            summaries["_outlook"] = outlook_obj
    except Exception as e:
        summaries["_outlook"] = {
            "top_risk": "Unable to generate outlook — check AI server.",
            "top_opportunity": None,
            "tax_watch": None,
            "action_items": [],
        }

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute(
            "INSERT OR REPLACE INTO news_summaries (day, summaries, generated_at) VALUES (?,?,?)",
            (today, json.dumps(summaries), now_str)
        )
        conn.commit()
        conn.close()

    return summaries


def generate_daily_insight(force: bool = False) -> dict:
    """
    Generate today's portfolio briefing by synthesizing specialist agent findings.
    Returns the insight dict. Stores in DB. Uses cached result if already run today.
    """
    _init_ai_tables()
    today = date.today().isoformat()

    # Return cached result if already generated today
    if not force and DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        row = conn.execute(
            "SELECT insight FROM ai_insights WHERE day=?", (today,)
        ).fetchone()
        conn.close()
        if row and row[0]:
            try:
                return json.loads(row[0])
            except Exception:
                pass

    if not ollama_client.available():
        return {"error": "AI model unavailable — check MLX server"}

    import macro_context
    import agent_db as _adb
    macro = macro_context.fetch()
    macro_block = macro.get("formatted_block", "Macro data unavailable.")

    # Portfolio summary: total value + layer weights with drift
    prices        = _get_holding_prices_from_db()
    layer_weights = _get_layer_weights_from_db()
    drift_alerts  = _get_drift_alerts(layer_weights)
    total_value   = sum(v.get("value", 0) or 0 for v in prices.values())

    layer_lines = ["PORTFOLIO SUMMARY:"]
    if total_value:
        layer_lines.append(f"  Total value: ${total_value:,.0f}")
    for label, data in sorted(layer_weights.items()):
        wt  = data.get("weight_pct", 0)
        chg = data.get("chg_pct", 0)
        layer_lines.append(f"  {label}: {wt:.1f}% actual ({chg:+.1f}% today)")
    if drift_alerts:
        layer_lines.append("  Drift alerts (≥5pp from target):")
        for d in drift_alerts:
            layer_lines.append(
                f"    {d['layer']}: {d['current']:.1f}% vs {d['target']:.0f}% target ({d['drift']:+.1f}pp)"
            )
    portfolio_summary_block = "\n".join(layer_lines)

    # Specialist agent findings (today's runs) + open recommendations
    agent_data = _adb.get_todays_findings()
    findings_by_agent = agent_data["findings"]
    open_recs = agent_data["recommendations"]

    findings_lines = ["SPECIALIST AGENT FINDINGS (today):"]
    if findings_by_agent:
        for agent_type, flist in sorted(findings_by_agent.items()):
            for f in flist:
                ticker_tag = f"[{f['ticker']}] " if f["ticker"] else ""
                sev = f["severity"]
                summary = (f["summary"] or "")[:200]
                why = (f["why_now"] or "")[:120]
                why_part = f" | {why}" if why else ""
                findings_lines.append(
                    f"  {agent_type}: {ticker_tag}{f['finding_type']} sev={sev} — {summary}{why_part}"
                )
    else:
        findings_lines.append("  No specialist findings recorded for today.")

    recs_lines = [f"\nOPEN RECOMMENDATIONS ({len(open_recs)} total):"]
    if open_recs:
        for r in open_recs[:20]:  # cap to avoid prompt bloat
            ticker = r["ticker"]
            action = r["action"]
            score  = r["score"]
            conf   = r["confidence"]
            pri    = r["priority"]
            agent  = r["agent_type"] or "?"
            why    = (r["why_now"] or "")[:160]
            rationale = (r["rationale"] or "")[:160]
            critic_v = r["critic_verdict"] or ""
            critic_o = (r["critic_objection"] or "")[:100]
            critic_part = f" | critic: {critic_v}" + (f" — {critic_o}" if critic_o else "") if critic_v else ""
            recs_lines.append(
                f"  [{ticker}] {action} | score={score} conf={conf} pri={pri} | {agent}{critic_part}"
            )
            if why:
                recs_lines.append(f"    why: {why}")
            if rationale and rationale != why:
                recs_lines.append(f"    rationale: {rationale}")
    else:
        recs_lines.append("  No open recommendations.")

    # News outlook summary (pre-computed — compact, no per-ticker details)
    news_block = ""
    news_summaries, _ = get_cached_news_summaries_today()
    if news_summaries and not news_summaries.get("_failed"):
        ol = news_summaries.get("_outlook") or {}
        news_lines = ["NEWS OUTLOOK (pre-computed highlights):"]
        if ol.get("top_risk"):
            news_lines.append(f"  Top risk: {ol['top_risk']}")
        if ol.get("top_opportunity"):
            news_lines.append(f"  Top opportunity: {ol['top_opportunity']}")
        if ol.get("tax_watch"):
            news_lines.append(f"  Tax watch: {ol['tax_watch']}")
        if ol.get("action_items"):
            for item in (ol["action_items"] or [])[:4]:
                news_lines.append(f"  - {item}")
        if len(news_lines) > 1:
            news_block = "\n".join(news_lines) + "\n\n"

    specialist_block = "\n".join(findings_lines) + "\n" + "\n".join(recs_lines)

    prompt = f"""You are a sophisticated investment advisor writing a daily portfolio briefing. Your job is to SYNTHESIZE the specialist agent findings below — not re-analyze the portfolio from scratch. Return ONLY valid JSON — no markdown, no extra text.

{macro_block}

{portfolio_summary_block}

{specialist_block}

{news_block}INSTRUCTIONS:
- Open with the most important issue flagged by specialist agents today
- Reference agents by name: "Guardian flagged GRMN...", "CC Agent recommends...", "Critic approved/rejected..."
- If critic reviewed a recommendation, include the verdict and key objection in risk_flags
- For tax_timing_note and tax_opportunity: use agent findings if available; otherwise note "No agent tax findings today"
- If no material findings exist, say so concisely ("No material specialist findings today — routine monitoring only")
- Do not invent risks not grounded in the findings above
- Do not give generic market commentary — tie every observation to specific tickers from the findings

Return exactly this JSON structure:
{{
  "macro_summary": "<2-3 sentence description of today's macro regime and its most relevant implication for this specific portfolio based on layer weights and any flagged drift>",
  "risk_flags": [
    "<agent name + ticker: specific risk from findings — e.g. 'Guardian flagged GRMN: 10Y yield at 4.7% compresses its growth multiple'>",
    "<agent name + ticker: recommendation with critic verdict if reviewed — e.g. 'CC Agent: SELL_CC on EW (score=78) — Critic APPROVED'>",
    "<additional finding or 'No further material risks flagged'>"
  ],
  "tax_timing_note": "<tax agent findings if any, or 'No agent tax findings today'>",
  "key_question": "<the single most important portfolio decision surfaced by today's agent findings — specific and actionable>",
  "tax_opportunity": "<specific ticker from tax agent findings, or 'None this week'>",
  "legislative_watch": "<apply the LEGISLATIVE CONNECTION RULE: only name a bill if it has a direct one-step impact on a specific held ticker's actual industry or business. Name the bill by ID, the holding, the mechanism, and the stage. If no bill qualifies, write 'No material legislation this week'>"
}}

{_LEG_RULE}"""

    # Log estimated prompt size vs old approach for token reduction verification
    est_tokens = len(prompt) // 4
    print(f"[DailyInsight] New prompt ~{est_tokens} tokens "
          f"({len(findings_by_agent)} agent types, {len(open_recs)} recs)")

    # Collect both reasoning and content tokens: Qwen3 thinking models sometimes
    # put the final answer in delta.reasoning tail (content stays empty when the
    # budget runs out). _extract_last_json then picks the LAST valid JSON with
    # the expected schema keys, skipping reasoning sketches with "..." placeholders.
    full_text = ""
    try:
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.3, num_predict=8000,
            enable_thinking=True
        ):
            full_text += tok
    except Exception as e:
        return {"error": f"AI generation failed: {e}"}

    insight = _extract_last_json(full_text, required_keys=["macro_summary", "risk_flags"])
    if insight is None:
        print(f"[DailyInsight] Parse failed. Raw output (first 600): {full_text[:600]!r}")
        return {"error": "AI returned malformed JSON", "raw": full_text[:500]}

    # Persist to DB
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    macro_snap = {k: v for k, v in macro.items() if k not in ("formatted_block", "headlines")}
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute(
            "INSERT OR REPLACE INTO ai_insights (day, insight, macro_snap, generated_at) VALUES (?,?,?,?)",
            (today, json.dumps(insight), json.dumps(macro_snap), now_str)
        )
        conn.commit()
        conn.close()

    return insight


# ── Holding macro scores ──────────────────────────────────────────────────────

def generate_holding_macro_scores(force: bool = False) -> dict:
    """
    Score each holding on 4 macro dimensions (1–10 scale).
    Batches tickers in groups of 8. Skips tickers scored within the last 7 days.
    Returns {ticker: {rate_sensitivity, inflation_hedge, dollar_sensitivity, geopolitical_risk, note}}.
    """
    _init_ai_tables()

    if not ollama_client.available():
        return {}

    holdings = _load_holdings_csv()
    if not holdings:
        return {}

    tickers = [_normalize_ticker(h.get("Stock", "")) for h in holdings if h.get("Stock")]
    tickers = list(dict.fromkeys(t for t in tickers if t))

    # Load existing scores from DB
    existing: dict = {}
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT ticker, scores, updated_at FROM holding_macro_scores").fetchall()
        conn.close()
        cutoff = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        for r in rows:
            if r["updated_at"] and r["updated_at"][:10] >= cutoff:
                try:
                    existing[_normalize_ticker(r["ticker"])] = json.loads(r["scores"])
                except Exception:
                    pass

    to_score = [t for t in tickers if force or t not in existing]
    if not to_score:
        return existing

    import macro_context
    macro = macro_context.fetch()
    macro_brief = (
        f"Current macro: VIX={macro.get('vix', 'N/A')}, "
        f"10Y yield={macro.get('yield_10y', 'N/A')}%, "
        f"Spread={macro.get('spread_bps', 'N/A')}bps ({macro.get('curve_interp', '')}), "
        f"CPI={macro.get('cpi_yoy', 'N/A')}% YoY, "
        f"Dollar={macro.get('dollar_interp', 'N/A')}"
    )

    results = dict(existing)
    BATCH = 1

    for i in range(0, len(to_score), BATCH):
        batch = to_score[i:i + BATCH]
        ticker_list = ", ".join(batch)

        dim_defs = "\n".join(
            f"- {dim}: {meta['prompt_def']}"
            for dim, meta in MACRO_DIMS.items()
        )
        prompt = f"""You are a quantitative analyst. Score each ticker on 4 macro risk dimensions from 1-10, with a specific reason for each score.

{macro_brief}

Scoring definitions (1=low, 10=high):
{dim_defs}

Tickers to score: {ticker_list}

Return ONLY valid JSON. Each dimension must include a score AND a one-sentence reason explaining specifically why that score applies to this ticker:
{{
  "TICKER1": {{
    "rate_sensitivity": {{"score": <1-10>, "reason": "<why this specific score for this ticker>"}},
    "inflation_hedge": {{"score": <1-10>, "reason": "<why this specific score for this ticker>"}},
    "dollar_sensitivity": {{"score": <1-10>, "reason": "<why this specific score for this ticker>"}},
    "geopolitical_risk": {{"score": <1-10>, "reason": "<why this specific score for this ticker>"}},
    "note": "<one sentence overall summary>"
  }}
}}"""

        # Wait for server to be ready before each batch (it may have restarted)
        for _attempt in range(30):
            if ollama_client.available():
                break
            time.sleep(5)
        else:
            print(f"[MacroScores] Server not ready for batch {i//BATCH+1}, skipping")
            continue

        full_text = ""
        try:
            for tok in ollama_client.stream_generate(
                prompt, model=ollama_client.DEFAULT_MODEL,
                temperature=0.2, num_predict=1600
            ):
                full_text += tok
        except Exception as e:
            print(f"[MacroScores] Batch {i//BATCH+1} failed: {e}")
            time.sleep(20)  # server likely restarted; give it time to reload
            continue

        batch_result = _extract_json(full_text)
        if batch_result is None:
            print(f"[MacroScores] Batch {i//BATCH+1} malformed JSON. Raw (first 400): {full_text[:400]!r}")
            time.sleep(20)  # server may have crashed during generation
            continue

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if DB_PATH.exists():
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            for ticker, scores in batch_result.items():
                ticker = _normalize_ticker(ticker)
                if ticker in tickers:
                    scores_json = json.dumps(scores)
                    conn.execute(
                        "INSERT OR REPLACE INTO holding_macro_scores (ticker, scores, updated_at) VALUES (?,?,?)",
                        (ticker, scores_json, now_str)
                    )
                    conn.execute(
                        "INSERT INTO holding_macro_scores_history (ticker, scores, scored_at) VALUES (?,?,?)",
                        (ticker, scores_json, now_str)
                    )
                    results[ticker] = scores
            conn.commit()
            conn.close()

        print(f"[MacroScores] Scored {len(batch_result)} tickers in batch {i//BATCH+1}")
        time.sleep(25)  # give server time to recover before next batch

    if to_score and results:
        generate_macro_score_summary(results, macro)

    return results


def generate_macro_score_summary(current_scores: dict, macro: dict) -> None:
    """
    After a scoring run, generate a per-layer AI narrative explaining what changed
    in the scores and why, based on the macro environment. Stores to DB.
    """
    if not DB_PATH.exists() or not current_scores:
        return
    if not ollama_client.available():
        return

    # ── Load previous scores (second-most-recent history entry per ticker) ──────
    prev_scores: dict = {}
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT ticker, scores FROM holding_macro_scores_history "
            "ORDER BY ticker, scored_at DESC"
        ).fetchall()
        conn.close()
        ticker_runs: dict = {}
        for r in rows:
            ticker_runs.setdefault(r["ticker"], []).append(r["scores"])
        for t, score_list in ticker_runs.items():
            if len(score_list) >= 2:
                try:
                    prev_scores[t] = json.loads(score_list[1])
                except Exception:
                    pass
    except Exception:
        pass

    def _composite(scores: dict):
        # Must match _compute_macro_composite in generate_dashboard.py exactly
        DIMS = [
            ("rate_sensitivity",   False),
            ("inflation_hedge",    True),
            ("dollar_sensitivity", False),
            ("geopolitical_risk",  False),
        ]
        parts = []
        for dim, is_benefit in DIMS:
            sv = _score_val(scores.get(dim))
            if sv is None:
                continue
            parts.append((sv - 1) / 9 if is_benefit else (10 - sv) / 9)
        return round(sum(parts) / len(parts) * 100) if parts else None

    # ── Load holdings to map ticker → layer number ───────────────────────────
    holdings_csv = _load_holdings_csv()
    ticker_layer: dict = {}
    for h in holdings_csv:
        t = _normalize_ticker(h.get("Stock", ""))
        if t:
            try:
                ticker_layer[t] = int(h.get("Layer", 0))
            except (TypeError, ValueError):
                pass

    # ── Group deltas by layer ────────────────────────────────────────────────
    layer_changes: dict = {}
    for ticker, scores in current_scores.items():
        layer_num = ticker_layer.get(ticker)
        if not layer_num:
            continue
        curr_c = _composite(scores)
        prev_s = prev_scores.get(ticker)
        prev_c = _composite(prev_s) if prev_s is not None else None
        delta_c = (curr_c - prev_c) if (curr_c is not None and prev_c is not None) else None

        dim_changes = []
        for dim in ("rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk"):
            cv = _score_val(scores.get(dim))
            pv = _score_val(prev_s.get(dim)) if prev_s is not None else None
            if cv is not None and pv is not None and cv != pv:
                dim_changes.append({
                    "dim":    dim,
                    "prev":   pv,
                    "curr":   cv,
                    "delta":  cv - pv,
                    "reason": _score_reason(scores.get(dim)),
                })

        layer_changes.setdefault(layer_num, []).append({
            "ticker":          ticker,
            "curr_composite":  curr_c,
            "prev_composite":  prev_c,
            "delta_composite": delta_c,
            "dim_changes":     dim_changes,
            "note":            scores.get("note", ""),
        })

    if not layer_changes:
        return

    # ── Build prompt ─────────────────────────────────────────────────────────
    macro_brief = (
        f"VIX={macro.get('vix','N/A')} ({macro.get('vix_interp','')}), "
        f"10Y={macro.get('yield_10y','N/A')}%, "
        f"Spread={macro.get('spread_bps','N/A')}bps ({macro.get('curve_interp','')}), "
        f"CPI={macro.get('cpi_yoy','N/A')}% YoY, "
        f"Dollar: {macro.get('dollar_interp','N/A')}, "
        f"Gold: {macro.get('gld_interp','N/A')}"
    )

    changes_block = ""
    for layer_num in sorted(layer_changes.keys()):
        layer_label = LAYER_NAMES.get(layer_num, f"L{layer_num}")
        changes_block += f"\nLayer {layer_num} — {layer_label}:\n"
        for item in layer_changes[layer_num]:
            prev_str = str(item["prev_composite"]) if item["prev_composite"] is not None else "—"
            delta_str = ""
            if item["delta_composite"] is not None:
                sign = "+" if item["delta_composite"] > 0 else ""
                delta_str = f" ({sign}{item['delta_composite']} vs last week)"
            elif item["prev_composite"] is None:
                delta_str = " (first score)"
            changes_block += f"  {item['ticker']}: composite {prev_str} → {item['curr_composite']}{delta_str}\n"
            for dc in item["dim_changes"]:
                sign = "+" if dc["delta"] > 0 else ""
                changes_block += f"    {dc['dim']}: {dc['prev']} → {dc['curr']} ({sign}{dc['delta']})"
                if dc["reason"]:
                    reason_short = dc["reason"][:80] + ("…" if len(dc["reason"]) > 80 else "")
                    changes_block += f" — {reason_short}"
                changes_block += "\n"
            if item.get("note"):
                changes_block += f"    Overall: {item['note']}\n"

    layer_json_template = ",\n    ".join(
        f'"{n}": "<2-3 sentences for layer {n}>"' for n in sorted(layer_changes.keys())
    )
    prompt = f"""You are a macro risk analyst reviewing weekly scoring updates for a layered investment portfolio.

MACRO ENVIRONMENT THIS WEEK:
{macro_brief}

SCORE CHANGES THIS RUN (composite is 0-100, higher = healthier; dimensions are 1-10):
{changes_block}

Write a concise weekly macro risk summary. For each layer listed, write 2-3 sentences covering: what changed in the scores, which holdings drove the change, and how the macro environment explains it. Also write 1-2 sentences summarizing the overall portfolio direction.

Return ONLY valid JSON, no extra text:
{{
  "portfolio": "<1-2 sentences on overall portfolio macro health direction>",
  "layers": {{
    {layer_json_template}
  }}
}}
"""

    for _attempt in range(3):
        if ollama_client.available():
            break
        time.sleep(5)
    else:
        print("[MacroSummary] Server not ready, skipping summary.")
        return

    try:
        result = ollama_client.generate_structured(
            prompt,
            schema={"portfolio": "", "layers": {}},
            model=ollama_client.DEFAULT_MODEL,
            temperature=0.3,
            num_predict=8000,
            retries=2,
        )
    except ollama_client.StructuredOutputError as e:
        print(f"[MacroSummary] AI call failed: {e}")
        return

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payload = {
        "portfolio":    result.get("portfolio", ""),
        "layers":       result.get("layers", {}),
        "scored_date":  date.today().isoformat(),
        "scored_count": sum(len(v) for v in layer_changes.values()),
    }
    conn = None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.execute(
            "INSERT INTO macro_score_summaries (summary_json, created_at) VALUES (?,?)",
            (json.dumps(payload), now_str)
        )
        conn.commit()
        print(f"[MacroSummary] Summary stored ({payload['scored_count']} holdings scored).")
    except Exception as e:
        print(f"[MacroSummary] DB write failed: {e}")
    finally:
        if conn:
            conn.close()


# ── Portfolio chat ────────────────────────────────────────────────────────────

def build_portfolio_system_prompt() -> str:
    """Build the system prompt for portfolio-level AI chat."""
    import macro_context
    macro = macro_context.fetch()

    holdings = _load_holdings_csv()
    prices   = _get_holding_prices_from_db()
    layer_weights = _get_layer_weights_from_db()
    drift_alerts  = _get_drift_alerts(layer_weights)

    # Load macro scores for context (compact=True omits per-dim reasons to keep prompt short)
    _, scores_block = _get_macro_scores_block(compact=True)

    cc_block       = _get_cc_context()
    lot_block      = _get_lot_context()
    realized_block = _get_realized_context()
    patterns_block = _get_behavior_patterns()
    personal_blocks = "\n\n".join(b for b in [cc_block, lot_block, realized_block, patterns_block] if b)

    framework = "\n".join(f"  {k}: {v}" for k, v in _LAYER_NAMES_LONG.items())

    system = f"""You are a sophisticated investment advisor helping the investor understand and manage their personal portfolio. You have deep knowledge of macro economics, geopolitics, tax strategy, and the portfolio framework below.

INVESTMENT FRAMEWORK:
{framework}

{_build_portfolio_block(holdings, prices)}

{_build_layer_block(layer_weights, drift_alerts)}

{macro.get('formatted_block', 'Macro data unavailable.')}
{scores_block}
{personal_blocks}

Rules for your responses:
- Always ground analysis in THIS specific portfolio — cite actual held tickers and their layers
- When discussing macro risks, connect them to specific positions the investor holds
- For CC questions, reference actual open positions by ticker and strike price
- For tax questions, reference actual lot dates and LT thresholds you have above
- Be direct and actionable; avoid vague generalities
- Keep responses focused and under ~300 words unless asked to elaborate"""

    return system


# ── CLI for standalone testing ────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", action="store_true", help="Generate macro scores for all holdings")
    parser.add_argument("--force",  action="store_true", help="Force regeneration even if cached")
    args = parser.parse_args()

    _init_ai_tables()

    if args.scores:
        print("Generating holding macro scores…")
        scores = generate_holding_macro_scores(force=args.force)
        for ticker, s in sorted(scores.items()):
            print(f"\n{ticker}:")
            for dim in SCORE_DIMS:
                raw = s.get(dim, '?')
                score = raw.get('score', '?') if isinstance(raw, dict) else raw
                reason = raw.get('reason', '') if isinstance(raw, dict) else ''
                line = f"  {SCORE_LABELS[dim]}: {score}/10"
                if reason:
                    line += f" — {reason}"
                print(line)
            print(f"  Note: {s.get('note', '')}")
    else:
        print("Generating daily portfolio insight…")
        insight = generate_daily_insight(force=args.force)
        if "error" in insight:
            print(f"ERROR: {insight['error']}")
        else:
            print(json.dumps(insight, indent=2))
