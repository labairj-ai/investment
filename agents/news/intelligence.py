"""
News intelligence pipeline: structured event extraction, thesis relevance mapping,
novelty/trend detection, deterministic materiality scoring, confirmation signals,
and portfolio theme detection.
"""
import hashlib
import json
import sqlite3
import sys
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

PROMPT_VERSION = "v1"

# ── Event taxonomy ────────────────────────────────────────────────────────────

EVENT_TAXONOMY = [
    "GUIDANCE_CHANGE", "EARNINGS", "MARGIN", "DEMAND",
    "CUSTOMER_WIN", "CUSTOMER_LOSS", "PRODUCT", "CAPEX",
    "M_AND_A", "MANAGEMENT", "REGULATORY", "LITIGATION",
    "SUPPLY_CHAIN", "COMPETITOR", "PRICING", "CREDIT_DEBT",
    "DIVIDEND_BUYBACK", "MACRO_EXPOSURE",
]

# Base materiality weight per event type (0.0–1.0)
_MATERIALITY: dict[str, float] = {
    "GUIDANCE_CHANGE":  0.90,
    "EARNINGS":         0.85,
    "M_AND_A":          0.85,
    "MARGIN":           0.80,
    "REGULATORY":       0.75,
    "LITIGATION":       0.70,
    "DEMAND":           0.70,
    "CUSTOMER_LOSS":    0.70,
    "CREDIT_DEBT":      0.65,
    "CUSTOMER_WIN":     0.65,
    "MANAGEMENT":       0.60,
    "PRICING":          0.60,
    "SUPPLY_CHAIN":     0.65,
    "CAPEX":            0.55,
    "COMPETITOR":       0.50,
    "DIVIDEND_BUYBACK": 0.50,
    "PRODUCT":          0.50,
    "MACRO_EXPOSURE":   0.45,
}
_MAGNITUDE_SCALE = {"LOW": 0.5, "MEDIUM": 0.75, "HIGH": 1.0}
_HORIZON_MULT    = {"IMMEDIATE": 1.0, "SHORT": 0.9, "MEDIUM": 0.75, "LONG": 0.5}
_NOVELTY_WT = {
    "NEW": 1.0, "CONFIRMING": 0.7, "ACCELERATING": 1.2,
    "REVERSING": 1.1, "FADING": 0.4, "RESOLVED": 0.2,
}
_PERSIST_ADJ = {
    "NEW": 1.0, "CONFIRMING": 1.1, "ACCELERATING": 1.3,
    "REVERSING": 1.0, "FADING": 0.6, "RESOLVED": 0.1,
}
_CONFIRM_BOOST = {
    "NEWS_ONLY": 1.0, "SOFT_CONFIRMATION": 1.3,
    "MULTI_SIGNAL_CONFIRMATION": 1.6, "CONTRADICTED": 0.7,
}

# Keyword sets for matching event types to thesis pillar/risk names
_EVENT_KEYWORDS: dict[str, list[str]] = {
    "GUIDANCE_CHANGE":  ["guidance", "forecast", "outlook", "target", "revenue guide"],
    "EARNINGS":         ["earnings", "eps", "profit", "income", "quarter", "results"],
    "MARGIN":           ["margin", "cost", "profitab", "operating income", "gross"],
    "DEMAND":           ["demand", "growth", "volume", "units sold", "sales", "order"],
    "REGULATORY":       ["regulat", "compliance", "government", "agency", "law", "ban"],
    "LITIGATION":       ["lawsuit", "litigat", "court", "settlement", "SEC", "probe"],
    "SUPPLY_CHAIN":     ["supply", "supplier", "inventory", "component", "shortage"],
    "MANAGEMENT":       ["CEO", "CFO", "executive", "management", "leadership", "board"],
    "M_AND_A":          ["acqui", "merger", "takeover", "deal", "divest", "spinoff"],
    "CUSTOMER_WIN":     ["contract", "customer", "win", "partnership", "deal signed"],
    "CUSTOMER_LOSS":    ["lost", "cancelled", "churn", "competitor won"],
    "CREDIT_DEBT":      ["debt", "credit", "bond", "rating", "leverage", "borrow"],
    "CAPEX":            ["capex", "capital expenditure", "invest", "expansion", "build"],
    "PRODUCT":          ["product", "launch", "feature", "platform", "service"],
    "PRICING":          ["price", "pricing", "tariff", "cost increase", "inflationary"],
    "COMPETITOR":       ["competitor", "market share", "rival", "compete"],
    "DIVIDEND_BUYBACK": ["dividend", "buyback", "repurchase", "payout", "yield"],
    "MACRO_EXPOSURE":   ["macro", "economic", "rate", "dollar", "inflation", "geopolit"],
}

# Thresholds for signal classification (portfolio_priority out of 100)
EMERGING_RISK_THRESHOLD = 45
EMERGING_OPP_THRESHOLD  = 45
THESIS_CHANGE_THRESHOLD = 25
PORTFOLIO_THEME_MIN     = 3


# ── Hash computation (0580) ───────────────────────────────────────────────────

def compute_news_hash(by_ticker: dict) -> str:
    """Deterministic SHA256 over article titles/sources/dates per ticker."""
    parts = []
    for ticker in sorted(by_ticker.keys()):
        for art in by_ticker[ticker]:
            parts.append((ticker, art.get("title", ""), art.get("source", ""),
                          art.get("pub_date", "")))
    payload = json.dumps(sorted(parts), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── LLM event extraction (0581) ───────────────────────────────────────────────

_TAXONOMY_LINE = ", ".join(EVENT_TAXONOMY)


def _build_event_extraction_prompt(by_ticker: dict) -> str:
    news_block = ""
    for ticker, items in by_ticker.items():
        news_block += f"\n{ticker}:\n"
        for art in items[:4]:
            src = art.get("source", "")
            title = art.get("title", "")
            body = art.get("body", "")
            excerpt = art.get("excerpt", "")
            detail = body[:120] if body else excerpt[:80] if excerpt else ""
            news_block += f"  [{src}] {title}\n"
            if detail:
                news_block += f"    {detail}\n"

    return f"""Extract structured investment events from news articles below.
Merge articles covering the same underlying fact into one event.
Return ONLY valid JSON. No markdown.

TAXONOMY: {_TAXONOMY_LINE}

NEWS:
{news_block.strip()}

Return this structure (0-5 events per ticker, only tickers with real events):
{{
  "TICKER": [
    {{
      "event_type": "GUIDANCE_CHANGE",
      "direction": "POSITIVE|NEGATIVE|MIXED|NEUTRAL",
      "magnitude": "LOW|MEDIUM|HIGH",
      "horizon": "IMMEDIATE|SHORT|MEDIUM|LONG",
      "confidence": 0.85,
      "affected_metric": "revenue guidance",
      "evidence": "one-sentence description of what happened with specifics",
      "titles": ["Article title 1", "Article title 2"]
    }}
  ]
}}"""


def extract_events_llm(by_ticker: dict, ollama_client_mod) -> dict[str, list[dict]]:
    """Call LLM to extract structured events from articles. Returns {ticker: [events]}."""
    if not by_ticker:
        return {}
    prompt = _build_event_extraction_prompt(by_ticker)
    raw = ""
    try:
        for tok in ollama_client_mod.stream_generate(
            prompt, model=ollama_client_mod.DEFAULT_MODEL,
            temperature=0.1, num_predict=3000,
        ):
            raw += tok
    except Exception as e:
        print(f"[NewsEvents] LLM extraction failed: {e}")
        return {}

    # Parse JSON from response
    raw = raw.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return {}
    try:
        parsed = json.loads(raw[start:end])
    except Exception:
        # Try stripping thinking blocks
        import re
        clean = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
        start = clean.find("{")
        end   = clean.rfind("}") + 1
        if start == -1 or end == 0:
            return {}
        try:
            parsed = json.loads(clean[start:end])
        except Exception:
            return {}

    if not isinstance(parsed, dict):
        return {}

    # Validate and normalise
    valid = {}
    for ticker, events in parsed.items():
        if not isinstance(events, list):
            continue
        clean_events = []
        for ev in events:
            if not isinstance(ev, dict):
                continue
            et = ev.get("event_type", "").upper()
            if et not in EVENT_TAXONOMY:
                et = "MACRO_EXPOSURE"
            direction  = ev.get("direction", "NEUTRAL").upper()
            if direction not in ("POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL"):
                direction = "NEUTRAL"
            magnitude  = ev.get("magnitude", "MEDIUM").upper()
            if magnitude not in ("LOW", "MEDIUM", "HIGH"):
                magnitude = "MEDIUM"
            horizon    = ev.get("horizon", "SHORT").upper()
            if horizon not in ("IMMEDIATE", "SHORT", "MEDIUM", "LONG"):
                horizon = "SHORT"
            conf       = float(ev.get("confidence", 0.7))
            conf       = max(0.0, min(1.0, conf))
            clean_events.append({
                "event_type":      et,
                "direction":       direction,
                "magnitude":       magnitude,
                "horizon":         horizon,
                "confidence":      conf,
                "affected_metric": str(ev.get("affected_metric", "") or ""),
                "evidence":        str(ev.get("evidence", "") or ""),
                "titles":          [str(t) for t in (ev.get("titles") or [])[:5]],
            })
        if clean_events:
            valid[ticker.upper()] = clean_events
    return valid


# ── Thesis relevance mapping (0582) ──────────────────────────────────────────

def _pillar_matches_event(pillar_name: str, risk_name: str, event_type: str) -> float:
    """Return relevance score 0.0-1.0 by keyword overlap."""
    text = (pillar_name + " " + risk_name).lower()
    keywords = _EVENT_KEYWORDS.get(event_type, [])
    if not keywords:
        return 0.0
    hits = sum(1 for kw in keywords if kw.lower() in text)
    return min(1.0, hits * 0.4)


def map_thesis_relevance(event_type: str, ticker: str) -> dict:
    """Look up ACTIVE thesis for ticker and return relevance mapping."""
    result = {
        "thesis_relevance": 0.0,
        "pillar_name": None,
        "risk_name": None,
        "catalyst_name": None,
        "trigger_proximity": 0.0,
    }
    try:
        sys.path.insert(0, str(PROJECT_DIR))
        import agent_db as _adb
        thesis = _adb.get_thesis(ticker)
        if not thesis or thesis.get("status") != "ACTIVE":
            return result
        pillars   = thesis.get("pillars", []) or []
        key_risks = thesis.get("key_risks", []) or []
        catalysts = thesis.get("catalysts", []) or []

        best_score = 0.0
        best_pillar = None
        for p in pillars:
            pname = p.get("name", "") or ""
            pdesc = p.get("description", "") or ""
            score = _pillar_matches_event(pname + " " + pdesc, "", event_type)
            # Scale by pillar importance (0–100 → 0–1)
            importance = float(p.get("importance", 20)) / 100
            score *= (0.5 + 0.5 * importance)
            if score > best_score:
                best_score = score
                best_pillar = pname

        best_risk = None
        for r in key_risks:
            rname = r if isinstance(r, str) else (r.get("name") or r.get("risk") or "")
            score = _pillar_matches_event(rname, "", event_type)
            if score > best_score:
                best_score = score
                best_risk = rname
                best_pillar = None

        best_catalyst = None
        for c in catalysts:
            cname = c if isinstance(c, str) else (c.get("description") or c.get("name") or "")
            score = _pillar_matches_event(cname, "", event_type)
            if score > 0.3 and best_score < 0.5:
                best_catalyst = cname

        # Trigger proximity: average of pillar health scores for matched pillar
        trigger_prox = 0.0
        if best_pillar:
            matched = [p for p in pillars if p.get("name") == best_pillar]
            if matched:
                p = matched[0]
                if p.get("status") == "VIOLATED":
                    trigger_prox = 1.0
                elif p.get("status") == "WARNING":
                    trigger_prox = 0.5

        result["thesis_relevance"]  = round(min(1.0, best_score), 3)
        result["pillar_name"]       = best_pillar
        result["risk_name"]         = best_risk
        result["catalyst_name"]     = best_catalyst
        result["trigger_proximity"] = trigger_prox
    except Exception:
        pass
    return result


# ── Trend detection (0583) ────────────────────────────────────────────────────

def compute_trend(ticker: str, event_type: str, direction: str,
                  today: str, conn: sqlite3.Connection) -> dict:
    """Query event history; return trend_status + occurrence counts."""
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    d7  = (today_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (today_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    d90 = (today_dt - timedelta(days=90)).strftime("%Y-%m-%d")

    try:
        row7  = conn.execute(
            "SELECT COUNT(*) FROM news_events WHERE ticker=? AND event_type=? "
            "AND direction=? AND day>=? AND day<?",
            (ticker, event_type, direction, d7, today)
        ).fetchone()
        row30 = conn.execute(
            "SELECT COUNT(*) FROM news_events WHERE ticker=? AND event_type=? "
            "AND direction=? AND day>=? AND day<?",
            (ticker, event_type, direction, d30, today)
        ).fetchone()
        row90 = conn.execute(
            "SELECT COUNT(*) FROM news_events WHERE ticker=? AND event_type=? "
            "AND direction=? AND day>=? AND day<?",
            (ticker, event_type, direction, d90, today)
        ).fetchone()
        # Opposite direction count (for REVERSING detection)
        opp_dir = "POSITIVE" if direction == "NEGATIVE" else ("NEGATIVE" if direction == "POSITIVE" else None)
        opp_30 = 0
        if opp_dir:
            opp_row = conn.execute(
                "SELECT COUNT(*) FROM news_events WHERE ticker=? AND event_type=? "
                "AND direction=? AND day>=? AND day<?",
                (ticker, event_type, opp_dir, d30, today)
            ).fetchone()
            opp_30 = opp_row[0] if opp_row else 0
    except Exception:
        return {"trend_status": "NEW", "occurrence_count_7d": 0,
                "occurrence_count_30d": 0, "occurrence_count_90d": 0}

    n7  = row7[0]  if row7  else 0
    n30 = row30[0] if row30 else 0
    n90 = row90[0] if row90 else 0

    if n30 == 0 and n90 == 0:
        trend = "NEW"
    elif opp_30 > 0 and n30 > 0:
        trend = "REVERSING"
    elif n7 >= 2 and n30 >= 3:
        trend = "ACCELERATING"
    elif n30 >= 2:
        trend = "CONFIRMING"
    elif n90 > 0 and n30 == 0:
        trend = "FADING"
    else:
        trend = "CONFIRMING"

    return {
        "trend_status":        trend,
        "occurrence_count_7d":  n7,
        "occurrence_count_30d": n30,
        "occurrence_count_90d": n90,
    }


# ── Deterministic scoring (0584) ─────────────────────────────────────────────

def score_event(event: dict, position_weight: float = 1.0) -> dict:
    """
    Compute signal_strength and portfolio_priority deterministically.
    position_weight is the holding's portfolio weight % (0–100).
    """
    et        = event.get("event_type", "MACRO_EXPOSURE")
    magnitude = event.get("magnitude", "MEDIUM")
    horizon   = event.get("horizon", "SHORT")
    conf      = float(event.get("confidence", 0.7))
    trend     = event.get("trend_status", "NEW")
    confirm   = event.get("confirmation_class", "NEWS_ONLY")
    thesis_rel = float(event.get("thesis_relevance", 0.0))
    trigger_px = float(event.get("trigger_proximity", 0.0))

    mat      = _MATERIALITY.get(et, 0.5)
    mag_sc   = _MAGNITUDE_SCALE.get(magnitude, 0.75)
    hor_mult = _HORIZON_MULT.get(horizon, 0.9)
    nov_wt   = _NOVELTY_WT.get(trend, 1.0)
    per_adj  = _PERSIST_ADJ.get(trend, 1.0)
    con_bst  = _CONFIRM_BOOST.get(confirm, 1.0)

    # Thesis relevance boosts materiality (max 20% boost)
    thesis_boost = 1.0 + 0.2 * thesis_rel

    raw_strength = (
        mat * mag_sc * hor_mult * conf
        * nov_wt * per_adj * con_bst * thesis_boost
    )
    # Normalize to 0–100
    signal_strength = min(100.0, raw_strength * 100.0)

    # Portfolio priority: scale by position weight (0-100 → fraction) + trigger boost
    pos_frac = min(1.0, position_weight / 100.0)
    trigger_bonus = 0.3 * trigger_px
    portfolio_priority = signal_strength * pos_frac * (1.0 + trigger_bonus)

    decomp = {
        "materiality":      round(mat, 3),
        "magnitude_scale":  round(mag_sc, 3),
        "horizon_mult":     round(hor_mult, 3),
        "confidence":       round(conf, 3),
        "novelty_weight":   round(nov_wt, 3),
        "persistence_adj":  round(per_adj, 3),
        "confirmation_boost": round(con_bst, 3),
        "thesis_boost":     round(thesis_boost, 3),
        "position_weight":  round(pos_frac, 3),
        "trigger_bonus":    round(trigger_bonus, 3),
    }

    return {
        "signal_strength":    round(signal_strength, 1),
        "portfolio_priority": round(portfolio_priority, 1),
        "score_decomposition": decomp,
    }


# ── Confirmation signals (0585) ───────────────────────────────────────────────

def _get_price_alpha(ticker: str, conn: sqlite3.Connection) -> dict:
    """Compute 1d/5d/20d alpha vs SPY from holding_day and spy_prices tables."""
    try:
        rows = conn.execute(
            "SELECT day, price FROM holding_day WHERE ticker=? AND price>0 "
            "ORDER BY day DESC LIMIT 25",
            (ticker,)
        ).fetchall()
        if len(rows) < 2:
            return {}
        days  = [r[0] for r in rows]
        spys  = conn.execute(
            f"SELECT day, price FROM spy_prices WHERE day IN ({','.join('?'*len(days))})",
            days
        ).fetchall()
        spy_map = {r[0]: r[1] for r in spys}

        def _pct_change(prices, n):
            if len(prices) < n + 1:
                return None
            return (prices[0] - prices[n]) / prices[n]

        ticker_prices = [r[1] for r in rows]
        spy_prices_seq = [spy_map.get(d) for d in days]
        spy_prices_seq = [p for p in spy_prices_seq if p is not None]

        alpha = {}
        for n, label in ((1, "1d"), (5, "5d"), (20, "20d")):
            tr = _pct_change(ticker_prices, n)
            sr = _pct_change(spy_prices_seq, n)
            if tr is not None and sr is not None:
                alpha[label] = round(tr - sr, 4)
        return alpha
    except Exception:
        return {}


def _get_thesis_health(ticker: str):
    """Return thesis health_score (0–100) for ticker, or None."""
    try:
        sys.path.insert(0, str(PROJECT_DIR))
        import agent_db as _adb
        t = _adb.get_thesis(ticker)
        if t and t.get("status") == "ACTIVE":
            return t.get("health_score")
    except Exception:
        pass
    return None


def _get_macro_score(ticker: str, conn: sqlite3.Connection) -> dict:
    """Return latest macro scores dict for ticker."""
    try:
        row = conn.execute(
            "SELECT scores FROM holding_macro_scores WHERE ticker=?", (ticker,)
        ).fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception:
        pass
    return {}


def attach_confirmation(event: dict, ticker: str, conn: sqlite3.Connection) -> dict:
    """
    Classify event as NEWS_ONLY / SOFT / MULTI_SIGNAL / CONTRADICTED.
    Returns dict with confirmation_class, confirmation_signals, skepticism_note.
    """
    direction  = event.get("direction", "NEUTRAL")
    event_type = event.get("event_type", "")

    alpha      = _get_price_alpha(ticker, conn)
    th_health  = _get_thesis_health(ticker)
    macro_sc   = _get_macro_score(ticker, conn)

    signals     = {}
    corroborating = 0
    contradicting = 0

    # Price alpha check (1d and 5d)
    for span in ("1d", "5d"):
        a = alpha.get(span)
        if a is None:
            continue
        signals[f"alpha_{span}"] = round(a * 100, 2)
        if direction == "NEGATIVE" and a < -0.005:
            corroborating += 1
        elif direction == "POSITIVE" and a > 0.005:
            corroborating += 1
        elif direction in ("NEGATIVE", "POSITIVE"):
            if (direction == "NEGATIVE" and a > 0.01) or (direction == "POSITIVE" and a < -0.01):
                contradicting += 1

    # Thesis health check
    if th_health is not None:
        signals["thesis_health"] = round(th_health, 1)
        if direction == "NEGATIVE" and th_health < 50:
            corroborating += 1
        elif direction == "POSITIVE" and th_health > 70:
            corroborating += 1
        elif direction == "NEGATIVE" and th_health > 75:
            contradicting += 1

    # Macro exposure (rate sensitivity for rate-driven events)
    if event_type == "MARGIN" and macro_sc:
        rate_sens = macro_sc.get("rate_sensitivity")
        if rate_sens is not None:
            signals["rate_sensitivity"] = rate_sens
            if direction == "NEGATIVE" and rate_sens >= 7:
                corroborating += 1

    # Trend-based corroboration
    trend = event.get("trend_status", "NEW")
    if trend in ("ACCELERATING", "CONFIRMING"):
        corroborating += 1

    # Classify
    if direction == "NEUTRAL" or direction == "MIXED":
        confirm_class = "NEWS_ONLY"
        skepticism = None
    elif contradicting > corroborating and contradicting >= 2:
        confirm_class = "CONTRADICTED"
        skepticism = (
            f"News is {direction.lower()} but "
            f"{'price trending positively' if alpha.get('5d', 0) > 0 else 'other signals positive'}. "
            "Weight with skepticism."
        )
    elif corroborating >= 3:
        confirm_class = "MULTI_SIGNAL_CONFIRMATION"
        skepticism = None
    elif corroborating >= 1:
        confirm_class = "SOFT_CONFIRMATION"
        skepticism = None
    else:
        confirm_class = "NEWS_ONLY"
        skepticism = None

    return {
        "confirmation_class":   confirm_class,
        "confirmation_signals": signals,
        "skepticism_note":      skepticism,
    }


# ── Portfolio theme detection (0585) ─────────────────────────────────────────

def detect_portfolio_themes(events_by_ticker: dict[str, list[dict]],
                             portfolio_weights: dict[str, float]) -> list[dict]:
    """
    Fire a PORTFOLIO_THEME alert when 3+ holdings share a causal event type.
    """
    from collections import defaultdict
    type_dir_map: dict[tuple, list[str]] = defaultdict(list)

    for ticker, events in events_by_ticker.items():
        seen = set()
        for ev in events:
            key = (ev["event_type"], ev["direction"])
            if key not in seen and ev.get("signal_strength", 0) >= 20:
                type_dir_map[key].append(ticker)
                seen.add(key)

    themes = []
    for (et, direction), tickers in type_dir_map.items():
        if len(tickers) < PORTFOLIO_THEME_MIN:
            continue
        combined_wt = sum(portfolio_weights.get(t, 0) for t in tickers)
        total_events = sum(
            1 for t in tickers
            for ev in events_by_ticker.get(t, [])
            if ev["event_type"] == et and ev["direction"] == direction
        )
        themes.append({
            "event_type":      et,
            "direction":       direction,
            "affected_tickers": tickers,
            "combined_weight":  round(combined_wt, 2),
            "event_count":     total_events,
            "description": (
                f"{len(tickers)} holdings show {direction.lower()} {et.lower().replace('_', ' ')} signals "
                f"(combined weight {combined_wt:.1f}%)"
            ),
        })

    return sorted(themes, key=lambda t: -t["combined_weight"])


# ── DB persistence ────────────────────────────────────────────────────────────

def persist_events(events_by_ticker: dict[str, list[dict]],
                   themes: list[dict],
                   day: str,
                   conn: sqlite3.Connection,
                   news_snapshot_hash: str = "") -> None:
    """Upsert news_events and news_portfolio_themes for the given day."""
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    # Delete today's existing events for these tickers before re-inserting
    tickers = list(events_by_ticker.keys())
    if tickers:
        placeholders = ",".join("?" * len(tickers))
        conn.execute(
            f"DELETE FROM news_events WHERE day=? AND ticker IN ({placeholders})",
            [day] + tickers,
        )

    for ticker, events in events_by_ticker.items():
        for ev in events:
            conn.execute(
                """INSERT OR REPLACE INTO news_events
                   (event_id, ticker, day, event_type, direction, magnitude,
                    expected_horizon, confidence, affected_metric, evidence_text,
                    source_titles, source_count, first_seen, last_seen,
                    thesis_relevance, pillar_name, risk_name, catalyst_name, trigger_proximity,
                    trend_status, occurrence_count_7d, occurrence_count_30d, occurrence_count_90d,
                    signal_strength, portfolio_priority, score_decomposition,
                    confirmation_class, confirmation_signals, skepticism_note,
                    news_snapshot_hash, extracted_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ev.get("event_id") or str(uuid.uuid4()),
                    ticker, day,
                    ev["event_type"], ev["direction"], ev["magnitude"],
                    ev["horizon"], ev["confidence"],
                    ev.get("affected_metric", ""),
                    ev.get("evidence", ""),
                    json.dumps(ev.get("titles", [])),
                    len(ev.get("titles", [])),
                    day, day,
                    ev.get("thesis_relevance", 0.0),
                    ev.get("pillar_name"),
                    ev.get("risk_name"),
                    ev.get("catalyst_name"),
                    ev.get("trigger_proximity", 0.0),
                    ev.get("trend_status", "NEW"),
                    ev.get("occurrence_count_7d", 0),
                    ev.get("occurrence_count_30d", 0),
                    ev.get("occurrence_count_90d", 0),
                    ev.get("signal_strength", 0.0),
                    ev.get("portfolio_priority", 0.0),
                    json.dumps(ev.get("score_decomposition", {})),
                    ev.get("confirmation_class", "NEWS_ONLY"),
                    json.dumps(ev.get("confirmation_signals", {})),
                    ev.get("skepticism_note"),
                    news_snapshot_hash,
                    now_str,
                ),
            )

    # Portfolio themes for today
    conn.execute("DELETE FROM news_portfolio_themes WHERE day=?", (day,))
    for th in themes:
        conn.execute(
            """INSERT INTO news_portfolio_themes
               (theme_id, day, event_type, direction, affected_tickers,
                combined_weight, event_count, description, detected_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), day,
                th["event_type"], th["direction"],
                json.dumps(th["affected_tickers"]),
                th["combined_weight"], th["event_count"],
                th["description"], now_str,
            ),
        )
    conn.commit()


# ── Main pipeline entry point ─────────────────────────────────────────────────

def run_pipeline(by_ticker: dict,
                 portfolio_weights: dict,
                 conn: sqlite3.Connection,
                 ollama_client_mod,
                 day=None):
    """
    Run the full news intelligence pipeline.
    Returns dict with: events_by_ticker, themes, news_snapshot_hash, article_count.
    """
    if day is None:
        day = date.today().isoformat()

    news_snapshot_hash = compute_news_hash(by_ticker)
    article_count = sum(len(v) for v in by_ticker.values())

    # Step 1: LLM event extraction (0581)
    raw_events = extract_events_llm(by_ticker, ollama_client_mod)
    if not raw_events:
        return {
            "events_by_ticker": {},
            "themes": [],
            "news_snapshot_hash": news_snapshot_hash,
            "article_count": article_count,
        }

    # Steps 2-6: enrich each event
    enriched: dict[str, list[dict]] = {}
    for ticker, events in raw_events.items():
        pos_wt = portfolio_weights.get(ticker, 0.0)
        ticker_events = []
        for ev in events:
            # 0582: thesis relevance
            thesis_info = map_thesis_relevance(ev["event_type"], ticker)
            ev.update(thesis_info)

            # 0583: trend detection
            trend_info = compute_trend(
                ticker, ev["event_type"], ev["direction"], day, conn
            )
            ev.update(trend_info)

            # 0585: confirmation (before scoring, since scoring uses it)
            confirm_info = attach_confirmation(ev, ticker, conn)
            ev.update(confirm_info)

            # 0584: score (after trend + confirmation)
            score_info = score_event(ev, position_weight=pos_wt)
            ev.update(score_info)

            ticker_events.append(ev)

        # Sort by portfolio_priority descending
        ticker_events.sort(key=lambda e: -e.get("portfolio_priority", 0))
        enriched[ticker] = ticker_events

    # Step 7: portfolio theme detection (0585)
    themes = detect_portfolio_themes(enriched, portfolio_weights)

    # Persist to DB
    try:
        persist_events(enriched, themes, day, conn, news_snapshot_hash)
    except Exception as e:
        print(f"[NewsIntelligence] Persist error: {e}")

    return {
        "events_by_ticker":  enriched,
        "themes":            themes,
        "news_snapshot_hash": news_snapshot_hash,
        "article_count":    article_count,
    }


def load_events_for_day(day: str, conn: sqlite3.Connection) -> dict:
    """Load persisted events and themes for a given day from DB."""
    try:
        rows = conn.execute(
            "SELECT * FROM news_events WHERE day=? ORDER BY portfolio_priority DESC",
            (day,)
        ).fetchall()
        events_by_ticker: dict[str, list[dict]] = {}
        for row in rows:
            d = dict(row)
            for json_field in ("source_titles", "score_decomposition", "confirmation_signals"):
                if d.get(json_field):
                    try:
                        d[json_field] = json.loads(d[json_field])
                    except Exception:
                        pass
            ticker = d["ticker"]
            events_by_ticker.setdefault(ticker, []).append(d)

        theme_rows = conn.execute(
            "SELECT * FROM news_portfolio_themes WHERE day=? ORDER BY combined_weight DESC",
            (day,)
        ).fetchall()
        themes = []
        for row in theme_rows:
            d = dict(row)
            if d.get("affected_tickers"):
                try:
                    d["affected_tickers"] = json.loads(d["affected_tickers"])
                except Exception:
                    pass
            themes.append(d)

        return {"events_by_ticker": events_by_ticker, "themes": themes}
    except Exception:
        return {"events_by_ticker": {}, "themes": []}
