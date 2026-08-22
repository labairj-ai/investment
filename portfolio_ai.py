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
    # The newsletter stores these in earn_alerts/exdiv_alerts but not in DB.
    # We skip this for now — the AI will note it can't see forward events.
    return []


# ── Prompt builders ───────────────────────────────────────────────────────────

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

    framework = "\n".join(f"  {k}: {v}" for k, v in LAYER_NAMES.items())

    prompt = f"""You are a sophisticated investment advisor analyzing a personal portfolio. Return ONLY valid JSON — no markdown, no extra text.

INVESTMENT FRAMEWORK (5-layer structure):
{framework}

{portfolio_block}

{layer_block}

{macro_block}

Analyze the portfolio through a macro lens. Consider how today's rate environment, inflation signals, dollar strength, geopolitical/trade risks, and volatility affect this SPECIFIC portfolio's holdings and layer structure.

Return exactly this JSON structure:
{{
  "macro_summary": "<2-3 sentence description of today's macro regime and its dominant investment implications>",
  "portfolio_macro_alignment": "<how well does this portfolio's current layer structure fit the macro environment? mention specific layers and why they are positioned well or poorly>",
  "risk_flags": [
    "<specific risk tied to a named holding or layer and a named macro factor>",
    "<another specific risk — e.g. 'L3 Compounders face headwind from rising real yields'>",
    "<geopolitical or trade risk affecting specific tickers if applicable>"
  ],
  "rebalancing_take": "<given the macro backdrop, is the current drift from targets a problem or actually defensible? be specific about which drifts matter most>",
  "tax_timing_note": "<any tax-timing consideration worth flagging — e.g. year-end harvesting, holding period milestones, capital gains distributions — or 'No immediate tax flags' if none>",
  "key_question": "<the single most important portfolio decision the investor should be thinking about this week, framed as a question>"
}}"""

    full_text = ""
    try:
        for tok in ollama_client.stream_generate(
            prompt, model=ollama_client.DEFAULT_MODEL,
            temperature=0.3, num_predict=1200
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

    framework = "\n".join(f"  {k}: {v}" for k, v in LAYER_NAMES.items())

    system = f"""You are a sophisticated investment advisor helping the investor understand and manage their personal portfolio. You have deep knowledge of macro economics, geopolitics, tax strategy, and the portfolio framework below.

INVESTMENT FRAMEWORK:
{framework}

{_build_portfolio_block(holdings, prices)}

{_build_layer_block(layer_weights, drift_alerts)}

{macro.get('formatted_block', 'Macro data unavailable.')}
{scores_block}
Rules for your responses:
- Always ground analysis in THIS specific portfolio — cite actual held tickers and their layers
- When discussing macro risks, connect them to specific positions the investor holds
- For tax questions, note that you don't have purchase date / cost-lot data unless told
- Be direct and actionable; avoid vague generalities
- When you don't know something (e.g. exact lot dates), say so and explain what data would help
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
