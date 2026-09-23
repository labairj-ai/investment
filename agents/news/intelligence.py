"""
News intelligence pipeline: structured event extraction, thesis relevance mapping,
novelty/trend detection, deterministic materiality scoring, confirmation signals,
and portfolio theme detection.
"""
import hashlib
import json
import re
import sqlite3
import sys
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent

NEWS_INTELLIGENCE_VERSION = "v1"
PROMPT_VERSION = "v1"

# ── Event taxonomy ────────────────────────────────────────────────────────────

EVENT_TAXONOMY = [
    "GUIDANCE_CHANGE", "EARNINGS", "MARGIN", "DEMAND",
    "CUSTOMER_WIN", "CUSTOMER_LOSS", "PRODUCT", "CAPEX",
    "M_AND_A", "MANAGEMENT", "REGULATORY", "LITIGATION",
    "SUPPLY_CHAIN", "COMPETITOR", "PRICING", "CREDIT_DEBT",
    "DIVIDEND_BUYBACK", "MACRO_EXPOSURE",
]

# Causal macro/cross-sector drivers (0593)
CAUSAL_DRIVER_VOCAB = [
    "AI_CAPEX", "USD_STRENGTH", "RATES_HIGHER", "RATES_LOWER",
    "CONSUMER_WEAKNESS", "CHINA_DEMAND", "FREIGHT_WEAKNESS",
    "ENERGY_INPUT_COST", "TARIFFS", "SUPPLY_CONSTRAINT",
    "CREDIT_TIGHTENING", "REGULATORY_PRESSURE", "OTHER",
]

# Base materiality weight per event type (0.0–1.0)
_MATERIALITY: dict = {
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

# Keyword sets for thesis component keyword retrieval (pre-filter for 0591)
_EVENT_KEYWORDS: dict = {
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

# Classification thresholds (use signal_strength, not portfolio_priority — 0588)
EMERGING_RISK_THRESHOLD = 45   # signal_strength threshold
EMERGING_OPP_THRESHOLD  = 45
THESIS_CHANGE_THRESHOLD = 25
PORTFOLIO_THEME_MIN     = 3


# ── Article identity (0589) ───────────────────────────────────────────────────

def _article_id(art: dict) -> str:
    """Deterministic SHA256[:16] ID for an article (url+source+pub_date+title)."""
    key = "|".join([
        art.get("url", ""),
        art.get("source", ""),
        art.get("pub_date", ""),
        art.get("title", ""),
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _build_article_manifest(by_ticker: dict) -> dict:
    """Return {article_id: {ticker, title, source, pub_date, url}} for all articles."""
    manifest = {}
    for ticker, articles in by_ticker.items():
        for art in articles:
            aid = _article_id(art)
            manifest[aid] = {
                "ticker": ticker,
                "title":    art.get("title", ""),
                "source":   art.get("source", ""),
                "pub_date": art.get("pub_date", ""),
                "url":      art.get("url", ""),
            }
    return manifest


def _event_fingerprint(ticker: str, event_type: str, direction: str,
                        affected_metric: str = "") -> str:
    """Stable 12-char fingerprint for the underlying business event."""
    key = f"{ticker}|{event_type}|{direction}|{(affected_metric or '').lower()[:40]}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# ── Hash computation (0580 + 0589 extension) ──────────────────────────────────

def compute_news_hash(by_ticker: dict) -> str:
    """SHA256 over url/title/source/pub_date/excerpt per ticker — covers full content."""
    parts = []
    for ticker in sorted(by_ticker.keys()):
        for art in by_ticker[ticker]:
            parts.append((
                ticker,
                art.get("url", ""),
                art.get("title", ""),
                art.get("source", ""),
                art.get("pub_date", ""),
                (art.get("excerpt") or art.get("body") or "")[:80],
            ))
    payload = json.dumps(sorted(parts), separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


# ── LLM event extraction (0581 + 0589 + 0593 extensions) ─────────────────────

_TAXONOMY_LINE     = ", ".join(EVENT_TAXONOMY)
_CAUSAL_DRIVER_LINE = ", ".join(CAUSAL_DRIVER_VOCAB)


def _build_event_extraction_prompt(by_ticker: dict, manifest: dict) -> str:
    """Build extraction prompt that includes article_ids and requests causal_driver."""
    news_block = ""
    for ticker, items in by_ticker.items():
        news_block += f"\n{ticker}:\n"
        for art in items[:4]:
            aid = _article_id(art)
            src = art.get("source", "")
            title = art.get("title", "")
            body = art.get("body", "")
            excerpt = art.get("excerpt", "")
            detail = body[:120] if body else excerpt[:80] if excerpt else ""
            news_block += f"  [id:{aid}] [{src}] {title}\n"
            if detail:
                news_block += f"    {detail}\n"

    return f"""Extract structured investment events from the news articles below.
Merge articles covering the same underlying fact into one event.
Return ONLY valid JSON. No markdown.

TAXONOMY: {_TAXONOMY_LINE}
CAUSAL_DRIVERS (optional): {_CAUSAL_DRIVER_LINE}

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
      "article_ids": ["<id from input>"],
      "causal_driver": "AI_CAPEX|USD_STRENGTH|null"
    }}
  ]
}}

Rules:
- article_ids must ONLY contain ids that appear as id:... in the input above
- causal_driver: only set when a macro/cross-sector driver clearly explains the event; null otherwise
- Merge articles about the same underlying fact into one event"""


def extract_events_llm(by_ticker: dict, ollama_client_mod) -> dict:
    """Call LLM to extract structured events. Returns {ticker: [events]} plus manifest."""
    if not by_ticker:
        return {}

    manifest = _build_article_manifest(by_ticker)
    valid_ids = set(manifest.keys())

    prompt = _build_event_extraction_prompt(by_ticker, manifest)
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

    raw = raw.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return {}
    try:
        parsed = json.loads(raw[start:end])
    except Exception:
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
            direction = ev.get("direction", "NEUTRAL").upper()
            if direction not in ("POSITIVE", "NEGATIVE", "MIXED", "NEUTRAL"):
                direction = "NEUTRAL"
            magnitude = ev.get("magnitude", "MEDIUM").upper()
            if magnitude not in ("LOW", "MEDIUM", "HIGH"):
                magnitude = "MEDIUM"
            horizon = ev.get("horizon", "SHORT").upper()
            if horizon not in ("IMMEDIATE", "SHORT", "MEDIUM", "LONG"):
                horizon = "SHORT"
            conf = float(ev.get("confidence", 0.7))
            conf = max(0.0, min(1.0, conf))

            # Validate article_ids against manifest (0589)
            raw_ids = ev.get("article_ids") or []
            validated_ids = [aid for aid in raw_ids if aid in valid_ids]

            # causal_driver (0593)
            cd = ev.get("causal_driver")
            if cd and cd.upper() in CAUSAL_DRIVER_VOCAB:
                causal_driver = cd.upper()
            else:
                causal_driver = None

            clean_events.append({
                "event_type":      et,
                "direction":       direction,
                "magnitude":       magnitude,
                "horizon":         horizon,
                "confidence":      conf,
                "affected_metric": str(ev.get("affected_metric", "") or ""),
                "evidence":        str(ev.get("evidence", "") or ""),
                "article_ids":     validated_ids,
                "causal_driver":   causal_driver,
                # titles kept for legacy display
                "titles": [
                    manifest[aid]["title"] for aid in validated_ids
                ] or [str(t) for t in (ev.get("titles") or [])[:5]],
            })
        if clean_events:
            valid[ticker.upper()] = clean_events

    # Attach manifest for provenance storage
    valid["_manifest"] = manifest
    return valid


# ── Thesis relevance mapping (0582 + 0591 LLM semantic mapper) ───────────────

def _pillar_matches_event(pillar_name: str, risk_name: str, event_type: str) -> float:
    """Return keyword-overlap relevance 0.0-1.0."""
    text = (pillar_name + " " + risk_name).lower()
    keywords = _EVENT_KEYWORDS.get(event_type, [])
    if not keywords:
        return 0.0
    hits = sum(1 for kw in keywords if kw.lower() in text)
    return min(1.0, hits * 0.4)


def _thesis_map_llm(event_type: str, direction: str, evidence: str,
                     affected_metric: str, candidates: list,
                     ollama_client_mod) -> dict:
    """LLM semantic pass: map event to best candidate thesis component (0591)."""
    if not candidates or not ollama_client_mod:
        return {}

    prompt = (
        f"Map this investment event to the most relevant thesis component.\n\n"
        f"Event: {event_type} ({direction})\n"
        f"Metric: {affected_metric}\n"
        f"Evidence: {evidence}\n\n"
        f"Candidate thesis components:\n{json.dumps(candidates, indent=2)}\n\n"
        f"Return ONLY JSON (no markdown):\n"
        f'{{"component_type":"pillar|risk|catalyst|trigger|none",'
        f'"component_name":"name or null",'
        f'"relationship":"STRENGTHENS|WEAKENS|SUPPORTS|CONTRADICTS|NONE",'
        f'"relevance":0.0,'
        f'"trigger_state":"NONE|APPROACHING|POSSIBLE_MATCH",'
        f'"explanation":"one sentence",'
        f'"confidence":0.0}}\n\n'
        f"Rules:\n"
        f"- trigger_state max is POSSIBLE_MATCH — never declare a trigger definitively fired\n"
        f"- relevance 0.0 if genuinely unrelated"
    )

    raw = ""
    try:
        for tok in ollama_client_mod.stream_generate(
            prompt, model=ollama_client_mod.DEFAULT_MODEL,
            temperature=0.1, num_predict=350,
        ):
            raw += tok
    except Exception:
        return {}

    raw = raw.strip()
    start = raw.find("{")
    end   = raw.rfind("}") + 1
    if start == -1 or end == 0:
        return {}
    try:
        r = json.loads(raw[start:end])
    except Exception:
        return {}

    # Validate relationship and trigger_state
    if r.get("relationship") not in ("STRENGTHENS", "WEAKENS", "SUPPORTS", "CONTRADICTS", "NONE"):
        r["relationship"] = "NONE"
    if r.get("trigger_state") not in ("NONE", "APPROACHING", "POSSIBLE_MATCH"):
        r["trigger_state"] = "NONE"
    r["relevance"] = max(0.0, min(1.0, float(r.get("relevance", 0.0))))
    r["confidence"] = max(0.0, min(1.0, float(r.get("confidence", 0.0))))
    return r


def map_thesis_relevance(event_type: str, ticker: str,
                          ev_evidence: str = "", ev_metric: str = "",
                          ev_direction: str = "NEUTRAL",
                          ollama_client_mod=None) -> dict:
    """Keyword pre-filter + optional LLM semantic mapping (0591)."""
    result = {
        "thesis_relevance":  0.0,
        "pillar_name":       None,
        "risk_name":         None,
        "catalyst_name":     None,
        "trigger_proximity": 0.0,
        "thesis_relationship": None,
        "thesis_trigger_state": "NONE",
        "thesis_explanation":   None,
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

        # Keyword pre-filter: score each component
        keyword_scored = []
        for p in pillars:
            pname = p.get("name", "") or ""
            pdesc = p.get("description", "") or ""
            score = _pillar_matches_event(pname + " " + pdesc, "", event_type)
            importance = float(p.get("importance", 20)) / 100
            score *= (0.5 + 0.5 * importance)
            if score > 0:
                keyword_scored.append({"type": "pillar", "name": pname,
                                        "score": score, "raw": p})

        for r in key_risks:
            rname = r if isinstance(r, str) else (r.get("name") or r.get("risk") or "")
            score = _pillar_matches_event(rname, "", event_type)
            if score > 0:
                keyword_scored.append({"type": "risk", "name": rname,
                                        "score": score, "raw": r})

        for c in catalysts:
            cname = c if isinstance(c, str) else (c.get("description") or c.get("name") or "")
            score = _pillar_matches_event(cname, "", event_type)
            if score > 0:
                keyword_scored.append({"type": "catalyst", "name": cname,
                                        "score": score, "raw": c})

        if not keyword_scored:
            return result

        keyword_scored.sort(key=lambda x: -x["score"])
        top_candidates = keyword_scored[:4]

        # Best from keyword pass
        best = top_candidates[0]
        best_score = best["score"]
        best_type  = best["type"]
        best_name  = best["name"]

        result["thesis_relevance"] = round(min(1.0, best_score), 3)
        if best_type == "pillar":
            result["pillar_name"] = best_name
        elif best_type == "risk":
            result["risk_name"] = best_name
        else:
            result["catalyst_name"] = best_name

        # Trigger proximity: based on pillar health (snapshot, not event-specific)
        trigger_prox = 0.0
        if best_type == "pillar":
            matched = [p for p in pillars if p.get("name") == best_name]
            if matched:
                p = matched[0]
                if p.get("status") == "VIOLATED":
                    trigger_prox = 1.0
                elif p.get("status") == "WARNING":
                    trigger_prox = 0.5
        result["trigger_proximity"] = trigger_prox

        # LLM semantic mapping (0591) — only when evidence available
        if ollama_client_mod and (ev_evidence or ev_metric):
            candidate_payload = [
                {"component_type": c["type"], "component_name": c["name"],
                 "description": c["raw"].get("description", "") if isinstance(c["raw"], dict) else ""}
                for c in top_candidates
            ]
            llm_result = _thesis_map_llm(
                event_type, ev_direction, ev_evidence, ev_metric,
                candidate_payload, ollama_client_mod
            )
            if llm_result and llm_result.get("relevance", 0) > 0:
                # LLM overrides keyword score when it has meaningful relevance
                rel = llm_result["relevance"]
                result["thesis_relevance"] = round(rel, 3)
                result["thesis_relationship"]  = llm_result.get("relationship")
                result["thesis_trigger_state"] = llm_result.get("trigger_state", "NONE")
                result["thesis_explanation"]   = llm_result.get("explanation")
                # Update trigger_proximity if LLM says APPROACHING/POSSIBLE_MATCH
                ts = llm_result.get("trigger_state", "NONE")
                if ts == "POSSIBLE_MATCH":
                    result["trigger_proximity"] = max(trigger_prox, 0.8)
                elif ts == "APPROACHING":
                    result["trigger_proximity"] = max(trigger_prox, 0.4)

    except Exception:
        pass
    return result


# ── Trend detection (0583 + 0590 fixes) ──────────────────────────────────────

def compute_trend(ticker: str, event_type: str, direction: str,
                  today: str, conn: sqlite3.Connection) -> dict:
    """
    Query event history; return trend_status + occurrence counts.
    Uses COUNT(DISTINCT event_fingerprint) to avoid media-recurrence inflation.
    FADING/RESOLVED are NOT returned here — those are decay states from the
    nightly sweep for tickers with no events today (see sweep_fading_resolved).
    """
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    d7  = (today_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (today_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    d90 = (today_dt - timedelta(days=90)).strftime("%Y-%m-%d")

    try:
        # Count distinct fingerprints (same underlying event counted once per period)
        row7 = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(event_fingerprint, event_id)) "
            "FROM news_events WHERE ticker=? AND event_type=? "
            "AND direction=? AND day>=? AND day<?",
            (ticker, event_type, direction, d7, today)
        ).fetchone()
        row30 = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(event_fingerprint, event_id)) "
            "FROM news_events WHERE ticker=? AND event_type=? "
            "AND direction=? AND day>=? AND day<?",
            (ticker, event_type, direction, d30, today)
        ).fetchone()
        row90 = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(event_fingerprint, event_id)) "
            "FROM news_events WHERE ticker=? AND event_type=? "
            "AND direction=? AND day>=? AND day<?",
            (ticker, event_type, direction, d90, today)
        ).fetchone()

        opp_dir = (
            "POSITIVE" if direction == "NEGATIVE"
            else "NEGATIVE" if direction == "POSITIVE"
            else None
        )
        opp_30 = 0
        if opp_dir:
            opp_row = conn.execute(
                "SELECT COUNT(DISTINCT COALESCE(event_fingerprint, event_id)) "
                "FROM news_events WHERE ticker=? AND event_type=? "
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

    # REVERSING must be checked BEFORE NEW — a first positive event after negative
    # history is REVERSING, not NEW (0590 fix: opposite-direction check runs first)
    if opp_30 > 0:
        trend = "REVERSING"
    elif n30 == 0 and n90 == 0:
        trend = "NEW"
    elif n7 >= 2 and n30 >= 3:
        trend = "ACCELERATING"
    elif n30 >= 2:
        trend = "CONFIRMING"
    elif n90 > 0 and n30 == 0:
        # Event reappearing after gap — it's CONFIRMING, not FADING
        # FADING/RESOLVED are generated by sweep_fading_resolved() for absent events
        trend = "CONFIRMING"
    else:
        trend = "CONFIRMING"

    return {
        "trend_status":         trend,
        "occurrence_count_7d":  n7,
        "occurrence_count_30d": n30,
        "occurrence_count_90d": n90,
    }


def sweep_fading_resolved(day: str, conn: sqlite3.Connection) -> None:
    """
    End-of-run sweep: mark previously active (ticker, event_type, direction) combos
    as FADING or RESOLVED when they are absent from today's events.
    FADING: active in last 30d, not today.
    RESOLVED: active 31-90d ago but not in last 30d and not today.
    """
    today_dt = datetime.strptime(day, "%Y-%m-%d")
    d30 = (today_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    d90 = (today_dt - timedelta(days=90)).strftime("%Y-%m-%d")
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    try:
        # Combos active in last 30d
        active_rows = conn.execute(
            "SELECT DISTINCT ticker, event_type, direction FROM news_events "
            "WHERE day>=? AND day<?",
            (d30, day)
        ).fetchall()

        # Combos seen today
        today_rows = conn.execute(
            "SELECT DISTINCT ticker, event_type, direction FROM news_events WHERE day=?",
            (day,)
        ).fetchall()
        today_set = {(r[0], r[1], r[2]) for r in today_rows}

        for row in active_rows:
            ticker, et, direction = row[0], row[1], row[2]
            if (ticker, et, direction) in today_set:
                continue  # Still active today

            # Determine FADING vs RESOLVED
            n30 = conn.execute(
                "SELECT COUNT(*) FROM news_events WHERE ticker=? AND event_type=? "
                "AND direction=? AND day>=? AND day<?",
                (ticker, et, direction, d30, day)
            ).fetchone()[0]
            n90 = conn.execute(
                "SELECT COUNT(*) FROM news_events WHERE ticker=? AND event_type=? "
                "AND direction=? AND day>=? AND day<?",
                (ticker, et, direction, d90, d30)
            ).fetchone()[0]

            new_status = "FADING" if n30 > 0 else ("RESOLVED" if n90 > 0 else None)
            if not new_status:
                continue

            # Insert a synthetic decay marker for today
            fp = _event_fingerprint(ticker, et, direction, "decay")
            conn.execute(
                """INSERT OR IGNORE INTO news_events
                   (event_id, ticker, day, event_type, direction, magnitude,
                    expected_horizon, confidence, trend_status,
                    occurrence_count_7d, occurrence_count_30d, occurrence_count_90d,
                    signal_strength, portfolio_priority,
                    news_snapshot_hash, event_fingerprint, extracted_at,
                    news_intelligence_version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid.uuid4()), ticker, day, et, direction,
                    "LOW", "SHORT", 0.5, new_status,
                    0, n30, n90,
                    0.0, 0.0,
                    "", fp, now_str,
                    NEWS_INTELLIGENCE_VERSION,
                ),
            )
        conn.commit()
    except Exception as e:
        print(f"[NewsIntelligence] Fading sweep error: {e}")


# ── Deterministic scoring (0584) ─────────────────────────────────────────────

def score_event(event: dict, position_weight: float = 1.0) -> dict:
    """
    Compute signal_strength and portfolio_priority deterministically.
    signal_strength is used for bucket classification (0588).
    portfolio_priority is signal_strength × position_weight × trigger_bonus,
    used for ordering within buckets only.
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
    thesis_boost = 1.0 + 0.2 * thesis_rel

    raw_strength = (
        mat * mag_sc * hor_mult * conf
        * nov_wt * per_adj * con_bst * thesis_boost
    )
    signal_strength = min(100.0, raw_strength * 100.0)

    pos_frac = min(1.0, position_weight / 100.0)
    trigger_bonus = 0.3 * trigger_px
    portfolio_priority = signal_strength * pos_frac * (1.0 + trigger_bonus)

    decomp = {
        "materiality":        round(mat, 3),
        "magnitude_scale":    round(mag_sc, 3),
        "horizon_mult":       round(hor_mult, 3),
        "confidence":         round(conf, 3),
        "novelty_weight":     round(nov_wt, 3),
        "persistence_adj":    round(per_adj, 3),
        "confirmation_boost": round(con_bst, 3),
        "thesis_boost":       round(thesis_boost, 3),
        "position_weight":    round(pos_frac, 3),
        "trigger_bonus":      round(trigger_bonus, 3),
    }

    return {
        "signal_strength":    round(signal_strength, 1),
        "portfolio_priority": round(portfolio_priority, 1),
        "score_decomposition": decomp,
    }


# ── Confirmation signals (0585 + 0592 fixes) ──────────────────────────────────

def _get_price_alpha(ticker: str, conn: sqlite3.Connection) -> dict:
    """
    Compute 1d/5d/20d alpha vs SPY using date-aligned pairs (0592 fix).
    Builds (date, ticker_price, spy_price) triplets joined on trading date.
    """
    try:
        rows = conn.execute(
            "SELECT day, price FROM holding_day WHERE ticker=? AND price>0 "
            "ORDER BY day DESC LIMIT 30",
            (ticker,)
        ).fetchall()
        if len(rows) < 2:
            return {}

        days = [r[0] for r in rows]
        spys = conn.execute(
            f"SELECT day, price FROM spy_prices WHERE day IN ({','.join('?'*len(days))})",
            days
        ).fetchall()
        spy_map = {r[0]: r[1] for r in spys}

        # Build aligned triplets — only dates present in BOTH series (0592 fix)
        aligned = [(r[0], r[1], spy_map[r[0]])
                   for r in rows if r[0] in spy_map and spy_map[r[0]] > 0]
        if len(aligned) < 2:
            return {}

        # aligned is sorted descending by day
        alpha = {}
        for n, label in ((1, "1d"), (5, "5d"), (20, "20d")):
            if len(aligned) < n + 1:
                continue
            t0, t_price0, s_price0 = aligned[0]
            tn, t_pricen, s_pricen = aligned[n]
            if t_pricen <= 0 or s_pricen <= 0:
                continue
            tr = (t_price0 - t_pricen) / t_pricen
            sr = (s_price0 - s_pricen) / s_pricen
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
    Confirmation channels: price/alpha, thesis health, macro state only.
    Trend is NOT a confirmation channel — it already affects signal_strength
    via novelty_weight and persistence_adj (0592 fix removes triple-count).
    """
    direction  = event.get("direction", "NEUTRAL")
    event_type = event.get("event_type", "")

    alpha      = _get_price_alpha(ticker, conn)
    th_health  = _get_thesis_health(ticker)
    macro_sc   = _get_macro_score(ticker, conn)

    signals     = {}
    corroborating = 0
    contradicting = 0

    # Price alpha check (independent channel 1)
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

    # Thesis health (independent channel 2)
    if th_health is not None:
        signals["thesis_health"] = round(th_health, 1)
        if direction == "NEGATIVE" and th_health < 50:
            corroborating += 1
        elif direction == "POSITIVE" and th_health > 70:
            corroborating += 1
        elif direction == "NEGATIVE" and th_health > 75:
            contradicting += 1

    # Macro exposure (independent channel 3)
    if event_type == "MARGIN" and macro_sc:
        rate_sens = macro_sc.get("rate_sensitivity")
        if rate_sens is not None:
            signals["rate_sensitivity"] = rate_sens
            if direction == "NEGATIVE" and rate_sens >= 7:
                corroborating += 1

    # NOTE: trend is intentionally NOT added as a corroboration channel (0592 fix)

    if direction in ("NEUTRAL", "MIXED"):
        confirm_class = "NEWS_ONLY"
        skepticism = None
    elif contradicting > corroborating and contradicting >= 2:
        confirm_class = "CONTRADICTED"
        a5 = alpha.get("5d", 0) or 0
        skepticism = (
            f"News is {direction.lower()} but "
            f"{'price trending positively' if a5 > 0 else 'other signals positive'}. "
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


# ── Portfolio theme detection (0585 + 0593 causal_driver) ─────────────────────

def detect_portfolio_themes(events_by_ticker: dict,
                             portfolio_weights: dict) -> list:
    """
    Fire a PORTFOLIO_THEME alert when 3+ holdings share the same causal_driver
    and direction (0593). Generic event_type grouping is not sufficient.
    Requires causal_driver != None and != OTHER.
    """
    causal_dir_map: dict = defaultdict(list)

    for ticker, events in events_by_ticker.items():
        seen = set()
        for ev in events:
            cd = ev.get("causal_driver")
            if not cd or cd == "OTHER":
                continue
            key = (cd, ev["direction"])
            if key not in seen and ev.get("signal_strength", 0) >= 20:
                causal_dir_map[key].append(ticker)
                seen.add(key)

    themes = []
    for (causal_driver, direction), tickers in causal_dir_map.items():
        if len(tickers) < PORTFOLIO_THEME_MIN:
            continue
        combined_wt = sum(portfolio_weights.get(t, 0) for t in tickers)
        total_events = sum(
            1 for t in tickers
            for ev in events_by_ticker.get(t, [])
            if ev.get("causal_driver") == causal_driver and ev["direction"] == direction
        )
        themes.append({
            "causal_driver":    causal_driver,
            "event_type":       causal_driver,  # kept for legacy display
            "direction":        direction,
            "affected_tickers": tickers,
            "combined_weight":  round(combined_wt, 2),
            "event_count":      total_events,
            "description": (
                f"{len(tickers)} holdings show {direction.lower()} "
                f"{causal_driver.lower().replace('_', ' ')} "
                f"(combined weight {combined_wt:.1f}%)"
            ),
        })

    return sorted(themes, key=lambda t: -t["combined_weight"])


# ── DB persistence (0589 + 0593 + 0594) ──────────────────────────────────────

def persist_events(events_by_ticker: dict,
                   themes: list,
                   day: str,
                   conn: sqlite3.Connection,
                   news_snapshot_hash: str = "",
                   manifest: Optional[dict] = None) -> None:
    """
    Upsert news_events and news_portfolio_themes for the given day.
    Preserves first_seen from prior rows with matching event_fingerprint (0589).
    """
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    tickers = list(events_by_ticker.keys())

    if tickers:
        placeholders = ",".join("?" * len(tickers))
        conn.execute(
            f"DELETE FROM news_events WHERE day=? AND ticker IN ({placeholders})",
            [day] + tickers,
        )

    for ticker, events in events_by_ticker.items():
        for ev in events:
            fingerprint = _event_fingerprint(
                ticker, ev["event_type"], ev["direction"],
                ev.get("affected_metric", "")
            )

            # Preserve first_seen from prior occurrences of same underlying event (0589)
            existing = conn.execute(
                "SELECT first_seen FROM news_events WHERE ticker=? AND event_fingerprint=? "
                "ORDER BY first_seen ASC LIMIT 1",
                (ticker, fingerprint)
            ).fetchone()
            first_seen = existing[0] if existing else day

            # article_ids_json: validated IDs from LLM (0589)
            article_ids = ev.get("article_ids", [])
            source_count = len(article_ids) if article_ids else max(1, len(ev.get("titles", [])))

            conn.execute(
                """INSERT OR REPLACE INTO news_events
                   (event_id, ticker, day, event_type, direction, magnitude,
                    expected_horizon, confidence, affected_metric, evidence_text,
                    source_titles, source_count, first_seen, last_seen,
                    thesis_relevance, pillar_name, risk_name, catalyst_name, trigger_proximity,
                    trend_status, occurrence_count_7d, occurrence_count_30d, occurrence_count_90d,
                    signal_strength, portfolio_priority, score_decomposition,
                    confirmation_class, confirmation_signals, skepticism_note,
                    news_snapshot_hash, extracted_at,
                    event_fingerprint, article_ids_json, causal_driver,
                    news_intelligence_version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    ev.get("event_id") or str(uuid.uuid4()),
                    ticker, day,
                    ev["event_type"], ev["direction"], ev["magnitude"],
                    ev["horizon"], ev["confidence"],
                    ev.get("affected_metric", ""),
                    ev.get("evidence", ""),
                    json.dumps(ev.get("titles", [])),
                    source_count,
                    first_seen, day,
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
                    fingerprint,
                    json.dumps(article_ids),
                    ev.get("causal_driver"),
                    NEWS_INTELLIGENCE_VERSION,
                ),
            )

    conn.execute("DELETE FROM news_portfolio_themes WHERE day=?", (day,))
    for th in themes:
        conn.execute(
            """INSERT INTO news_portfolio_themes
               (theme_id, day, event_type, direction, affected_tickers,
                combined_weight, event_count, description, detected_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid.uuid4()), day,
                th.get("causal_driver", th["event_type"]), th["direction"],
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

    # Step 1: LLM event extraction (0581 + 0589 article IDs)
    extraction_result = extract_events_llm(by_ticker, ollama_client_mod)
    manifest = extraction_result.pop("_manifest", {})
    raw_events = extraction_result
    if not raw_events:
        return {
            "events_by_ticker": {},
            "themes": [],
            "news_snapshot_hash": news_snapshot_hash,
            "article_count": article_count,
        }

    # Steps 2-6: enrich each event
    enriched: dict = {}
    for ticker, events in raw_events.items():
        pos_wt = portfolio_weights.get(ticker, 0.0)
        ticker_events = []
        for ev in events:
            # 0582+0591: thesis relevance (with LLM semantic mapping)
            thesis_info = map_thesis_relevance(
                ev["event_type"], ticker,
                ev_evidence=ev.get("evidence", ""),
                ev_metric=ev.get("affected_metric", ""),
                ev_direction=ev.get("direction", "NEUTRAL"),
                ollama_client_mod=ollama_client_mod,
            )
            ev.update(thesis_info)

            # 0583+0590: trend detection (fixed ordering)
            trend_info = compute_trend(
                ticker, ev["event_type"], ev["direction"], day, conn
            )
            ev.update(trend_info)

            # 0585+0592: confirmation (trend removed from channels)
            confirm_info = attach_confirmation(ev, ticker, conn)
            ev.update(confirm_info)

            # 0584: score (after trend + confirmation)
            score_info = score_event(ev, position_weight=pos_wt)
            ev.update(score_info)

            ticker_events.append(ev)

        ticker_events.sort(key=lambda e: -e.get("portfolio_priority", 0))
        enriched[ticker] = ticker_events

    # Step 7: portfolio theme detection (0593 causal_driver-based)
    themes = detect_portfolio_themes(enriched, portfolio_weights)

    # Persist to DB
    try:
        persist_events(enriched, themes, day, conn, news_snapshot_hash, manifest)
    except Exception as e:
        print(f"[NewsIntelligence] Persist error: {e}")

    # Step 8: fading/resolved sweep (0590)
    try:
        sweep_fading_resolved(day, conn)
    except Exception as e:
        print(f"[NewsIntelligence] Fading sweep error: {e}")

    return {
        "events_by_ticker":  enriched,
        "themes":            themes,
        "news_snapshot_hash": news_snapshot_hash,
        "article_count":    article_count,
        "_manifest":        manifest,
    }


def load_events_for_day(day: str, conn: sqlite3.Connection) -> dict:
    """Load persisted events and themes for a given day from DB."""
    try:
        rows = conn.execute(
            "SELECT * FROM news_events WHERE day=? ORDER BY portfolio_priority DESC",
            (day,)
        ).fetchall()
        events_by_ticker: dict = {}
        for row in rows:
            d = dict(row)
            for json_field in ("source_titles", "score_decomposition",
                               "confirmation_signals", "article_ids_json"):
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
