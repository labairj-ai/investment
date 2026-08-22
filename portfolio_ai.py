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

LAYER_NAMES = {
    1: "L1 Structural Ballast (stability anchor, ~25% target — broad index, bonds)",
    2: "L2 Cash-Flow Engines (income generators, ~20% target — dividend stocks, REITs)",
    3: "L3 Compounders (growth compounders, ~35% target — quality growth businesses)",
    4: "L4 Convexity (high-upside asymmetric bets, ~12% target — concentrated growth/speculative)",
    5: "L5 Shock Absorbers (portfolio hedges, ~8% target — gold, cash, inverse ETFs)",
}

SCORE_DIMS = ["rate_sensitivity", "inflation_hedge", "dollar_sensitivity", "geopolitical_risk"]
SCORE_LABELS = {
    "rate_sensitivity":  "Rate (hurt by rising rates)",
    "inflation_hedge":   "Inflation hedge (benefits from inflation)",
    "dollar_sensitivity":"Dollar (hurt by strong dollar)",
    "geopolitical_risk": "Geopolitical / trade risk",
}


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
    conn.commit()
    conn.close()


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
    TARGETS = {
        "Layer 1: L1 Structural Ballast": 25.0,
        "Layer 2: L2 Cash-Flow Engines":  20.0,
        "Layer 3: L3 Compounders":        35.0,
        "Layer 4: L4 Convexity":          12.0,
        "Layer 5: L5 Shock Absorbers":     8.0,
    }
    alerts = []
    for layer_label, data in layer_weights.items():
        target = TARGETS.get(layer_label)
        if target is None:
            continue
        drift = data["weight_pct"] - target
        if abs(drift) >= 5.0:
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

def get_cached_insight_today() -> dict | None:
    """Return today's cached insight from DB, or None if not yet generated."""
    _init_ai_tables()
    today = date.today().isoformat()
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        row = conn.execute("SELECT insight FROM ai_insights WHERE day=?", (today,)).fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def get_cached_news_summaries_today() -> dict | None:
    """Return today's cached per-ticker news summaries from DB, or None."""
    _init_ai_tables()
    today = date.today().isoformat()
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=5)
        row = conn.execute("SELECT summaries FROM news_summaries WHERE day=?", (today,)).fetchone()
        conn.close()
        if row and row[0]:
            return json.loads(row[0])
    except Exception:
        pass
    return None


def generate_news_summaries(force: bool = False) -> dict:
    """
    For each holding that has recent news, generate an AI summary of the
    headlines plus a macro-angle sentence.  Returns {ticker: {summary, macro_angle}}.
    Cached in DB by day.
    """
    _init_ai_tables()
    today = date.today().isoformat()

    if not force:
        cached = get_cached_news_summaries_today()
        if cached is not None:
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

    import macro_context
    macro = macro_context.fetch()
    macro_block = macro.get("formatted_block", "Macro data unavailable.")

    news_block = ""
    for ticker, items in tickers_with_news.items():
        news_block += f"\n{ticker}:\n"
        for item in items[:6]:
            src = item.get("source", "")
            news_block += f"  [{src}] {item.get('title', '')}\n"

    prompt = f"""You are a financial analyst summarizing recent news for a personal investor's portfolio holdings.

CURRENT MACRO ENVIRONMENT:
{macro_block}

RECENT NEWS BY HOLDING:
{news_block}

For each ticker listed above, write:
1. A concise 2-3 sentence summary of the key news themes — reference specific headlines
2. 1-2 sentences on how the current macro environment is specifically relevant to this stock

Return ONLY valid JSON — no markdown, no extra text:
{{
  "TICKER": {{
    "summary": "<2-3 sentence news summary referencing actual headlines>",
    "macro_angle": "<how today's macro environment — rates, VIX, dollar strength, sector trends — directly affects this holding>"
  }}
}}

Only include tickers present in the news above. Be specific, not generic."""

    full_text = ""
    try:
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.3, num_predict=4000
        ):
            full_text += tok
    except Exception as e:
        return {"error": f"AI generation failed: {e}"}

    try:
        dec = json.JSONDecoder()
        start = full_text.index("{")
        summaries, _ = dec.raw_decode(full_text, start)
    except (ValueError, json.JSONDecodeError):
        return {"error": "AI returned malformed JSON", "raw": full_text[:500]}

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
    Generate today's macro-aware portfolio insight.
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
    macro = macro_context.fetch()

    holdings = _load_holdings_csv()
    prices   = _get_holding_prices_from_db()
    layer_weights = _get_layer_weights_from_db()
    drift_alerts  = _get_drift_alerts(layer_weights)

    portfolio_block = _build_portfolio_block(holdings, prices)
    layer_block     = _build_layer_block(layer_weights, drift_alerts)
    macro_block     = macro.get("formatted_block", "Macro data unavailable.")
    cc_block        = _get_cc_context()
    lot_block       = _get_lot_context()
    realized_block  = _get_realized_context()
    patterns_block  = _get_behavior_patterns()

    framework = "\n".join(f"  {k}: {v}" for k, v in LAYER_NAMES.items())

    personal_blocks = "\n\n".join(b for b in [cc_block, lot_block, realized_block, patterns_block] if b)

    # Pull holding-specific news headlines into the prompt
    news_block = _get_news_block(holdings)

    prompt = f"""You are a sophisticated investment advisor analyzing a personal portfolio. Return ONLY valid JSON — no markdown, no extra text.

INVESTMENT FRAMEWORK (5-layer structure):
{framework}

{portfolio_block}

{layer_block}

{macro_block}

{personal_blocks}
{news_block}
IMPORTANT — be specific, not generic:
- Reference holdings by ticker name (e.g. BRK-B, SCHD, GRMN), not just by layer
- Connect macro signals to SPECIFIC held positions and their current macro scores
- For CC commentary, reference actual open positions by ticker and strike price
- For tax timing, reference specific tickers and their lot dates or LT thresholds
- Acknowledge accumulation patterns where relevant (e.g. SCHD as DRIP position)
- Do not give generic market commentary — tie every observation to THIS portfolio

Return exactly this JSON structure:
{{
  "macro_summary": "<2-3 sentence description of today's macro regime and its dominant investment implications for this portfolio>",
  "portfolio_macro_alignment": "<how well does this portfolio fit the macro environment? name specific tickers and layers — well positioned or at risk and why>",
  "risk_flags": [
    "<specific risk: name the ticker or layer AND the macro driver — e.g. 'GRMN (L3) faces dollar headwind as strong USD compresses international revenue'>",
    "<another specific risk referencing actual held names>",
    "<geopolitical or trade risk naming specific exposed tickers>"
  ],
  "rebalancing_take": "<given the macro backdrop, is the current layer drift defensible or a problem? name specific drifting layers and whether the macro supports holding that tilt>",
  "tax_timing_note": "<name specific tickers and lot dates worth acting on — approaching LT thresholds, TLH candidates, or realized gain offsets — or 'No immediate tax flags'>",
  "key_question": "<the single most important portfolio decision for this week — specific and actionable, not generic>",
  "cc_program_note": "<observation about the active CC positions — strike selection vs current prices, income generated, which 100+ share holdings could expand the program>",
  "tax_opportunity": "<specific ticker + lot date combination worth acting on for tax optimization, or 'None this week'>"
}}"""

    full_text = ""
    try:
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.3, num_predict=2000
        ):
            full_text += tok
    except Exception as e:
        return {"error": f"AI generation failed: {e}"}

    try:
        dec = json.JSONDecoder()
        start = full_text.index("{")
        insight, _ = dec.raw_decode(full_text, start)
    except (ValueError, json.JSONDecodeError):
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

    tickers = [str(h.get("Stock", "")).strip().upper() for h in holdings if h.get("Stock")]
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
                    existing[r["ticker"]] = json.loads(r["scores"])
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
    BATCH = 8

    for i in range(0, len(to_score), BATCH):
        batch = to_score[i:i + BATCH]
        ticker_list = ", ".join(batch)

        prompt = f"""You are a quantitative analyst. Score each ticker on 4 macro risk dimensions from 1-10.

{macro_brief}

Scoring definitions (1=low, 10=high):
- rate_sensitivity: How much does a 50bps rate RISE hurt this position? (10=very hurt, e.g. long-duration bonds, REITs, high-PE growth; 1=immune or benefits, e.g. short-duration, banks)
- inflation_hedge: How well does this position benefit from sustained inflation? (10=strong hedge, e.g. gold, commodities, energy, TIPS; 1=hurt by inflation, e.g. fixed-income, long-duration)
- dollar_sensitivity: How much does a strong dollar hurt this position? (10=very hurt, e.g. multinational exporters, EM exposure; 1=immune or benefits, e.g. US domestic services, importers)
- geopolitical_risk: How exposed is this position to trade wars, tariffs, or geopolitical disruption? (10=high exposure, e.g. China-exposed tech, global supply chains; 1=low, e.g. domestic utilities, US healthcare)

Tickers to score: {ticker_list}

Return ONLY valid JSON:
{{
  "TICKER1": {{"rate_sensitivity": <1-10>, "inflation_hedge": <1-10>, "dollar_sensitivity": <1-10>, "geopolitical_risk": <1-10>, "note": "<one sentence summary>"}},
  "TICKER2": {{"rate_sensitivity": <1-10>, "inflation_hedge": <1-10>, "dollar_sensitivity": <1-10>, "geopolitical_risk": <1-10>, "note": "<one sentence summary>"}}
}}"""

        full_text = ""
        try:
            for tok in ollama_client.stream_generate(
                prompt, model=ollama_client.DEFAULT_MODEL,
                temperature=0.2, num_predict=900
            ):
                full_text += tok
        except Exception as e:
            print(f"[MacroScores] Batch {i//BATCH+1} failed: {e}")
            continue

        try:
            dec = json.JSONDecoder()
            start = full_text.index("{")
            batch_result, _ = dec.raw_decode(full_text, start)
        except (ValueError, json.JSONDecodeError):
            print(f"[MacroScores] Batch {i//BATCH+1} returned malformed JSON")
            continue

        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if DB_PATH.exists():
            conn = sqlite3.connect(str(DB_PATH), timeout=10)
            for ticker, scores in batch_result.items():
                ticker = ticker.strip().upper()
                if ticker in tickers:
                    conn.execute(
                        "INSERT OR REPLACE INTO holding_macro_scores (ticker, scores, updated_at) VALUES (?,?,?)",
                        (ticker, json.dumps(scores), now_str)
                    )
                    results[ticker] = scores
            conn.commit()
            conn.close()

        print(f"[MacroScores] Scored {len(batch_result)} tickers in batch {i//BATCH+1}")
        time.sleep(1)

    return results


# ── Portfolio chat ────────────────────────────────────────────────────────────

def build_portfolio_system_prompt() -> str:
    """Build the system prompt for portfolio-level AI chat."""
    import macro_context
    macro = macro_context.fetch()

    holdings = _load_holdings_csv()
    prices   = _get_holding_prices_from_db()
    layer_weights = _get_layer_weights_from_db()
    drift_alerts  = _get_drift_alerts(layer_weights)

    # Load macro scores for context
    scores_block = ""
    if DB_PATH.exists():
        conn = sqlite3.connect(str(DB_PATH), timeout=10)
        conn.row_factory = sqlite3.Row
        score_rows = conn.execute("SELECT ticker, scores FROM holding_macro_scores").fetchall()
        conn.close()
        if score_rows:
            scores_block = "\nMACRO RISK SCORES (1-10 scale, higher = more exposed):\n"
            for r in score_rows:
                try:
                    s = json.loads(r["scores"])
                    scores_block += (
                        f"  {r['ticker']}: rate={s.get('rate_sensitivity','?')} "
                        f"inflation={s.get('inflation_hedge','?')} "
                        f"dollar={s.get('dollar_sensitivity','?')} "
                        f"geo={s.get('geopolitical_risk','?')} — {s.get('note','')}\n"
                    )
                except Exception:
                    pass

    cc_block       = _get_cc_context()
    lot_block      = _get_lot_context()
    realized_block = _get_realized_context()
    patterns_block = _get_behavior_patterns()
    personal_blocks = "\n\n".join(b for b in [cc_block, lot_block, realized_block, patterns_block] if b)

    framework = "\n".join(f"  {k}: {v}" for k, v in LAYER_NAMES.items())

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
                print(f"  {SCORE_LABELS[dim]}: {s.get(dim, '?')}/10")
            print(f"  Note: {s.get('note', '')}")
    else:
        print("Generating daily portfolio insight…")
        insight = generate_daily_insight(force=args.force)
        if "error" in insight:
            print(f"ERROR: {insight['error']}")
        else:
            print(json.dumps(insight, indent=2))
