"""
News intelligence pipeline v2.

0596-0600: canonical snapshot contract, fail-closed grounding,
real event identity + decay state, complete thesis contract,
true confirmation channels + per-event bucketing.

v1 → v2: changed provenance (canonical snapshot), event identity (causal_event_key),
         decay semantics (news_event_state), thesis contract, confirmation channels.
No v1 rows in production DB as of 2026-09-23 — clean bump.
"""
from __future__ import annotations

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

NEWS_INTELLIGENCE_VERSION = "v2"
PROMPT_VERSION = "v1"

# ── Event taxonomy ────────────────────────────────────────────────────────────

EVENT_TAXONOMY = [
    "GUIDANCE_CHANGE", "EARNINGS", "MARGIN", "DEMAND",
    "CUSTOMER_WIN", "CUSTOMER_LOSS", "PRODUCT", "CAPEX",
    "M_AND_A", "MANAGEMENT", "REGULATORY", "LITIGATION",
    "SUPPLY_CHAIN", "COMPETITOR", "PRICING", "CREDIT_DEBT",
    "DIVIDEND_BUYBACK", "MACRO_EXPOSURE",
]

CAUSAL_DRIVER_VOCAB = [
    "AI_CAPEX", "USD_STRENGTH", "RATES_HIGHER", "RATES_LOWER",
    "CONSUMER_WEAKNESS", "CHINA_DEMAND", "FREIGHT_WEAKNESS",
    "ENERGY_INPUT_COST", "TARIFFS", "SUPPLY_CONSTRAINT",
    "CREDIT_TIGHTENING", "REGULATORY_PRESSURE", "OTHER",
]

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

EMERGING_RISK_THRESHOLD = 45
EMERGING_OPP_THRESHOLD  = 45
THESIS_CHANGE_THRESHOLD = 25
PORTFOLIO_THEME_MIN     = 3


# ── Article identity ──────────────────────────────────────────────────────────

def _article_id(art: dict) -> str:
    key = "|".join([
        art.get("url", ""),
        art.get("source", ""),
        art.get("pub_date", ""),
        art.get("title", ""),
    ])
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _build_article_manifest(by_ticker: dict) -> dict:
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
    key = f"{ticker}|{event_type}|{direction}|{(affected_metric or '').lower()[:40]}"
    return hashlib.sha256(key.encode()).hexdigest()[:12]


# ── Canonical NewsSnapshot contract (0596) ────────────────────────────────────

def build_news_snapshot(by_ticker: dict) -> dict:
    """
    Build a canonical NewsSnapshot after enrichment.
    model_input_text = exact bytes supplied to the LLM (body[:120] else excerpt[:80]).
    Hash covers full model_input_text — body changes past char 80 now invalidate cache.
    Returns {snapshot_id, captured_at, articles: [...], snapshot_hash}.
    """
    articles = []
    for ticker in sorted(by_ticker.keys()):
        for art in by_ticker[ticker]:
            aid = _article_id(art)
            body    = art.get("body", "") or ""
            excerpt = art.get("excerpt", "") or ""
            model_input_text = body[:120] if body else excerpt[:80]
            content_hash = hashlib.sha256(
                (art.get("url", "") + model_input_text).encode()
            ).hexdigest()[:16]
            articles.append({
                "article_id":       aid,
                "ticker":           ticker,
                "url":              art.get("url", ""),
                "source":           art.get("source", ""),
                "published_at":     art.get("pub_date", ""),
                "title":            art.get("title", ""),
                "model_input_text": model_input_text,
                "content_hash":     content_hash,
            })

    payload = json.dumps(
        [(a["article_id"], a["model_input_text"]) for a in articles],
        separators=(",", ":"),
    )
    snapshot_hash = hashlib.sha256(payload.encode()).hexdigest()[:16]

    return {
        "snapshot_id":   str(uuid.uuid4()),
        "captured_at":   datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "articles":      articles,
        "snapshot_hash": snapshot_hash,
    }


def compute_news_hash(by_ticker: dict) -> str:
    """Thin wrapper around build_news_snapshot for backward compatibility."""
    return build_news_snapshot(by_ticker)["snapshot_hash"]


# ── LLM event extraction (0596-0597: canonical snapshot + fail-closed) ────────

_TAXONOMY_LINE      = ", ".join(EVENT_TAXONOMY)
_CAUSAL_DRIVER_LINE = ", ".join(CAUSAL_DRIVER_VOCAB)


def _build_event_extraction_prompt(by_ticker: dict, manifest: dict) -> str:
    news_block = ""
    for ticker, items in by_ticker.items():
        news_block += f"\n{ticker}:\n"
        for art in items[:4]:
            aid    = _article_id(art)
            src    = art.get("source", "")
            title  = art.get("title", "")
            body   = art.get("body", "")
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
      "causal_driver": "AI_CAPEX|USD_STRENGTH|null",
      "causal_event_key": "TICKER_SHORT_EVENT_DESCRIPTION_IN_CAPS"
    }}
  ]
}}

Rules:
- article_ids must ONLY contain ids that appear as id:... in the input above
- Only include tickers that appear in the input above
- causal_driver: only set when a macro/cross-sector driver clearly explains the event; null otherwise
- causal_event_key: stable identifier for the underlying business event (e.g. META_FY27_AI_CAPEX_RAISE); max 60 chars uppercase; null if unclear
- Merge articles about the same underlying fact into one event"""


def extract_events_llm(by_ticker: dict, ollama_client_mod,
                        manifest: Optional[dict] = None) -> dict:
    """
    Call LLM to extract structured events. Fail-closed validation (0597):
    - Unknown ticker → reject event
    - Cross-ticker article ID → reject that ID
    - Zero valid same-ticker IDs → reject event
    - No title-string fallback for structured events
    """
    if not by_ticker:
        return {}

    if manifest is None:
        manifest = _build_article_manifest(by_ticker)

    valid_tickers = {t.upper() for t in by_ticker.keys()}

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

    valid: dict = {}
    for ticker, events in parsed.items():
        event_ticker = ticker.upper()

        # 0597: reject unknown tickers
        if event_ticker not in valid_tickers:
            continue

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

            # 0597: validate article_ids — only IDs belonging to this ticker
            raw_ids = ev.get("article_ids") or []
            validated_ids = [
                aid for aid in raw_ids
                if aid in manifest and manifest[aid]["ticker"].upper() == event_ticker
            ]

            # 0597: reject event with zero valid same-ticker article IDs
            if not validated_ids:
                continue

            # causal_driver (0593)
            cd = ev.get("causal_driver")
            causal_driver = cd.upper() if cd and cd.upper() in CAUSAL_DRIVER_VOCAB else None

            # causal_event_key (0598): LLM-supplied opaque event identity string
            cek = ev.get("causal_event_key")
            if cek:
                cek = str(cek).upper().strip()[:60]
                if not cek:
                    cek = None
            else:
                cek = None

            # Titles derived exclusively from validated manifest entries (0597: no fallback)
            titles = [manifest[aid]["title"] for aid in validated_ids if manifest.get(aid)]

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
                "causal_event_key": cek,
                "titles":          titles,
            })
        if clean_events:
            valid[event_ticker] = clean_events

    valid["_manifest"] = manifest
    return valid


# ── Thesis relevance mapping (0599: complete thesis contract) ─────────────────

def _pillar_matches_event(pillar_name: str, risk_name: str, event_type: str) -> float:
    text = (pillar_name + " " + risk_name).lower()
    keywords = _EVENT_KEYWORDS.get(event_type, [])
    if not keywords:
        return 0.0
    hits = sum(1 for kw in keywords if kw.lower() in text)
    return min(1.0, hits * 0.4)


def _thesis_map_llm(event_type: str, direction: str, evidence: str,
                     affected_metric: str, candidates: list,
                     ollama_client_mod) -> dict:
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

    if r.get("relationship") not in ("STRENGTHENS", "WEAKENS", "SUPPORTS", "CONTRADICTS", "NONE"):
        r["relationship"] = "NONE"
    if r.get("trigger_state") not in ("NONE", "APPROACHING", "POSSIBLE_MATCH"):
        r["trigger_state"] = "NONE"
    r["relevance"]   = max(0.0, min(1.0, float(r.get("relevance", 0.0))))
    r["confidence"]  = max(0.0, min(1.0, float(r.get("confidence", 0.0))))
    return r


def map_thesis_relevance(event_type: str, ticker: str,
                          ev_evidence: str = "", ev_metric: str = "",
                          ev_direction: str = "NEUTRAL",
                          ollama_client_mod=None) -> dict:
    """
    Keyword pre-filter + optional LLM semantic mapping.
    0599: includes review_triggers/ADD/TRIM/EXIT candidates; after LLM call,
    pillar_name/risk_name/catalyst_name reflects LLM's chosen component;
    separates pillar_health_state from event_trigger_state/event_trigger_proximity.
    """
    result = {
        "thesis_relevance":       0.0,
        "pillar_name":            None,
        "risk_name":              None,
        "catalyst_name":          None,
        "trigger_proximity":      0.0,   # kept for schema compat; scoring uses event_trigger_proximity
        "pillar_health_state":    None,  # snapshot of matched pillar status
        "event_trigger_state":    "NONE",
        "event_trigger_proximity": 0.0,
        "thesis_relationship":    None,
        "thesis_trigger_state":   "NONE",
        "thesis_explanation":     None,
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

        # 0599: include review_triggers and ADD/TRIM/EXIT conditions as candidates
        review_triggers_raw = thesis.get("review_triggers")
        if review_triggers_raw:
            if isinstance(review_triggers_raw, str):
                try:
                    review_triggers_raw = json.loads(review_triggers_raw)
                except Exception:
                    review_triggers_raw = [review_triggers_raw]
        review_triggers = review_triggers_raw if isinstance(review_triggers_raw, list) else []

        add_condition  = thesis.get("add_condition", "") or ""
        trim_condition = thesis.get("trim_condition", "") or ""
        exit_condition = thesis.get("exit_condition", "") or ""

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

        # 0599: review_triggers
        for trig in review_triggers:
            tname = trig if isinstance(trig, str) else str(trig)
            score = _pillar_matches_event(tname, "", event_type)
            if score > 0:
                keyword_scored.append({"type": "trigger", "name": tname,
                                        "score": score, "raw": {"description": tname}})

        # 0599: ADD/TRIM/EXIT conditions
        for cond_type, cond_text in [
            ("add_condition", add_condition),
            ("trim_condition", trim_condition),
            ("exit_condition", exit_condition),
        ]:
            if cond_text:
                score = _pillar_matches_event(cond_text, "", event_type)
                if score > 0:
                    keyword_scored.append({"type": cond_type, "name": cond_text[:60],
                                            "score": score, "raw": {"description": cond_text}})

        if not keyword_scored:
            return result

        keyword_scored.sort(key=lambda x: -x["score"])
        top_candidates = keyword_scored[:4]
        best = top_candidates[0]

        result["thesis_relevance"] = round(min(1.0, best["score"]), 3)

        # Set the matching name field from keyword pass (will be overridden by LLM below)
        _set_component_name(result, best["type"], best["name"])

        # 0599: pillar_health_state — snapshot of current pillar health, independent of event
        if best["type"] == "pillar":
            matched = [p for p in pillars if p.get("name") == best["name"]]
            if matched:
                result["pillar_health_state"] = matched[0].get("status") or "ON_TRACK"

        # LLM semantic mapping (0591+0599) — only when evidence available
        if ollama_client_mod and (ev_evidence or ev_metric):
            candidate_payload = [
                {
                    "component_type": c["type"],
                    "component_name": c["name"],
                    "description": c["raw"].get("description", "") if isinstance(c["raw"], dict) else "",
                }
                for c in top_candidates
            ]
            llm_result = _thesis_map_llm(
                event_type, ev_direction, ev_evidence, ev_metric,
                candidate_payload, ollama_client_mod,
            )
            if llm_result and llm_result.get("relevance", 0) > 0:
                rel = llm_result["relevance"]
                result["thesis_relevance"]   = round(rel, 3)
                result["thesis_relationship"] = llm_result.get("relationship")
                result["thesis_explanation"]  = llm_result.get("explanation")

                # 0599: update pillar/risk/catalyst_name from LLM's chosen component
                llm_ctype = llm_result.get("component_type", "none")
                llm_cname = llm_result.get("component_name")
                if llm_cname and llm_ctype != "none":
                    # Validate against candidate list before accepting
                    candidate_names = {c["name"] for c in top_candidates}
                    if llm_cname in candidate_names:
                        # Clear all, then set the LLM's chosen one
                        result["pillar_name"]    = None
                        result["risk_name"]      = None
                        result["catalyst_name"]  = None
                        _set_component_name(result, llm_ctype, llm_cname)
                        # Update pillar_health_state if LLM chose a pillar
                        if llm_ctype == "pillar":
                            matched = [p for p in pillars if p.get("name") == llm_cname]
                            if matched:
                                result["pillar_health_state"] = matched[0].get("status") or "ON_TRACK"
                        else:
                            result["pillar_health_state"] = None

                # 0599: event_trigger_state and event_trigger_proximity from LLM
                ts = llm_result.get("trigger_state", "NONE")
                result["event_trigger_state"] = ts
                result["thesis_trigger_state"] = ts
                if ts == "POSSIBLE_MATCH":
                    result["event_trigger_proximity"] = 0.8
                elif ts == "APPROACHING":
                    result["event_trigger_proximity"] = 0.4
                else:
                    result["event_trigger_proximity"] = 0.0

    except Exception:
        pass
    return result


def _set_component_name(result: dict, comp_type: str, comp_name: str) -> None:
    """Set the appropriate name field; clear others. Handles extended component types."""
    if comp_type == "pillar":
        result["pillar_name"] = comp_name
    elif comp_type == "risk":
        result["risk_name"] = comp_name
    elif comp_type in ("catalyst", "add_condition", "trim_condition", "exit_condition", "trigger"):
        result["catalyst_name"] = comp_name


# ── Trend detection (0598: count distinct causal_event_key) ──────────────────

def compute_trend(ticker: str, event_type: str, direction: str,
                  today: str, conn: sqlite3.Connection) -> dict:
    """
    Query event history; return trend_status + occurrence counts.
    0598: counts distinct causal_event_key (with fingerprint/event_id fallback)
    so the same underlying business event is never double-counted.
    FADING/RESOLVED come from news_event_state, not from this function.
    """
    today_dt = datetime.strptime(today, "%Y-%m-%d")
    d7  = (today_dt - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (today_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    d90 = (today_dt - timedelta(days=90)).strftime("%Y-%m-%d")

    try:
        row7 = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(causal_event_key, event_fingerprint, event_id)) "
            "FROM news_events WHERE ticker=? AND event_type=? "
            "AND direction=? AND day>=? AND day<?",
            (ticker, event_type, direction, d7, today)
        ).fetchone()
        row30 = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(causal_event_key, event_fingerprint, event_id)) "
            "FROM news_events WHERE ticker=? AND event_type=? "
            "AND direction=? AND day>=? AND day<?",
            (ticker, event_type, direction, d30, today)
        ).fetchone()
        row90 = conn.execute(
            "SELECT COUNT(DISTINCT COALESCE(causal_event_key, event_fingerprint, event_id)) "
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
                "SELECT COUNT(DISTINCT COALESCE(causal_event_key, event_fingerprint, event_id)) "
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

    # REVERSING check before NEW — first positive after negative history (0590 fix)
    if opp_30 > 0:
        trend = "REVERSING"
    elif n30 == 0 and n90 == 0:
        trend = "NEW"
    elif n7 >= 2 and n30 >= 3:
        trend = "ACCELERATING"
    elif n30 >= 2:
        trend = "CONFIRMING"
    else:
        trend = "CONFIRMING"

    return {
        "trend_status":         trend,
        "occurrence_count_7d":  n7,
        "occurrence_count_30d": n30,
        "occurrence_count_90d": n90,
    }


def update_event_state_sweep(day: str, conn: sqlite3.Connection) -> None:
    """
    Update news_event_state for all known causal_event_keys (0598).
    NEVER inserts synthetic rows into news_events.

    State machine:
    - Real event today         → ACTIVE
    - Absent ≤30d from last seen → FADING
    - Absent >30d from last seen → RESOLVED
    """
    today_dt = datetime.strptime(day, "%Y-%m-%d")
    d30 = (today_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS news_event_state (
            ticker            TEXT NOT NULL,
            causal_event_key  TEXT NOT NULL,
            last_real_seen_at TEXT NOT NULL,
            state             TEXT NOT NULL DEFAULT 'ACTIVE',
            state_as_of       TEXT NOT NULL,
            PRIMARY KEY (ticker, causal_event_key)
        )""")

        # Mark events seen today as ACTIVE
        today_keys = conn.execute(
            "SELECT DISTINCT ticker, causal_event_key FROM news_events "
            "WHERE day=? AND causal_event_key IS NOT NULL",
            (day,)
        ).fetchall()

        for ticker, key in today_keys:
            conn.execute(
                """INSERT OR REPLACE INTO news_event_state
                   (ticker, causal_event_key, last_real_seen_at, state, state_as_of)
                   VALUES (?, ?, ?, 'ACTIVE', ?)""",
                (ticker, key, day, now_str),
            )

        today_set = {(r[0], r[1]) for r in today_keys}

        # Discover all known causal_event_keys from news_events history (last 90d)
        # and register/update their state, even if not yet in news_event_state
        d90 = (today_dt - timedelta(days=90)).strftime("%Y-%m-%d")
        historical = conn.execute(
            "SELECT DISTINCT ticker, causal_event_key, MAX(day) as last_real "
            "FROM news_events WHERE causal_event_key IS NOT NULL AND day >= ? "
            "GROUP BY ticker, causal_event_key",
            (d90,)
        ).fetchall()

        for ticker, key, last_real in historical:
            if (ticker, key) in today_set:
                continue  # Already registered as ACTIVE above
            new_state = "FADING" if last_real >= d30 else "RESOLVED"
            # INSERT if new, otherwise UPDATE if state has changed
            conn.execute(
                """INSERT OR REPLACE INTO news_event_state
                   (ticker, causal_event_key, last_real_seen_at, state, state_as_of)
                   VALUES (?, ?, ?, ?, ?)""",
                (ticker, key, last_real, new_state, now_str),
            )

        # Also decay existing state table entries not covered by news_events history
        stale_rows = conn.execute(
            "SELECT ticker, causal_event_key, last_real_seen_at FROM news_event_state "
            "WHERE state != 'RESOLVED'"
        ).fetchall()
        historical_set = {(r[0], r[1]) for r in historical}
        for ticker, key, last_seen in stale_rows:
            if (ticker, key) in today_set or (ticker, key) in historical_set:
                continue
            new_state = "FADING" if last_seen >= d30 else "RESOLVED"
            conn.execute(
                "UPDATE news_event_state SET state=?, state_as_of=? "
                "WHERE ticker=? AND causal_event_key=?",
                (new_state, now_str, ticker, key),
            )

        conn.commit()
    except Exception as e:
        print(f"[NewsIntelligence] Event state sweep error: {e}")


# Backward-compat alias — call site in run_pipeline now uses update_event_state_sweep
sweep_fading_resolved = update_event_state_sweep


# ── Deterministic scoring (0599: trigger_bonus uses event_trigger_proximity) ──

def score_event(event: dict, position_weight: float = 1.0) -> dict:
    """
    Compute signal_strength and portfolio_priority deterministically.
    0599: trigger_bonus reads event_trigger_proximity (event-specific LLM value),
    not the old pillar-health-based trigger_proximity.
    """
    et        = event.get("event_type", "MACRO_EXPOSURE")
    magnitude = event.get("magnitude", "MEDIUM")
    horizon   = event.get("horizon", "SHORT")
    conf      = float(event.get("confidence", 0.7))
    trend     = event.get("trend_status", "NEW")
    confirm   = event.get("confirmation_class", "NEWS_ONLY")
    thesis_rel = float(event.get("thesis_relevance", 0.0))
    # 0599: use event_trigger_proximity (LLM-derived), not trigger_proximity (pillar health)
    trigger_px = float(event.get("event_trigger_proximity", 0.0))

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


# ── Confirmation signals (0600: true independent channels) ────────────────────

def _get_price_alpha(ticker: str, conn: sqlite3.Connection) -> dict:
    """Compute 1d/5d/20d alpha vs SPY using date-aligned pairs (0592)."""
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

        aligned = [(r[0], r[1], spy_map[r[0]])
                   for r in rows if r[0] in spy_map and spy_map[r[0]] > 0]
        if len(aligned) < 2:
            return {}

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


def _get_thesis_health(ticker: str) -> Optional[float]:
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
    try:
        row = conn.execute(
            "SELECT scores FROM holding_macro_scores WHERE ticker=?", (ticker,)
        ).fetchone()
        if row and row[0]:
            return json.loads(row[0])
    except Exception:
        pass
    return {}


def _get_fundamentals_trend(ticker: str, conn: sqlite3.Connection) -> Optional[str]:
    """
    Revenue trend from financial pipeline — stub for FUNDAMENTALS channel (0600).
    Returns 'positive', 'negative', or None.
    """
    try:
        rows = conn.execute(
            "SELECT period_end, revenue FROM company_financials "
            "WHERE ticker=? AND period_type='Q' AND revenue IS NOT NULL "
            "ORDER BY period_end DESC LIMIT 2",
            (ticker,)
        ).fetchall()
        if len(rows) < 2 or rows[1][1] is None or rows[1][1] == 0:
            return None
        growth = (rows[0][1] - rows[1][1]) / abs(rows[1][1])
        if growth > 0.03:
            return "positive"
        if growth < -0.03:
            return "negative"
        return None
    except Exception:
        return None


def _get_agent_findings_flag(ticker: str, conn: sqlite3.Connection) -> Optional[str]:
    """Agent findings channel stub (0600). Returns None until Guardian wiring lands."""
    return None


def attach_confirmation(event: dict, ticker: str, conn: sqlite3.Connection) -> dict:
    """
    Classify event as NEWS_ONLY / SOFT / MULTI_SIGNAL / CONTRADICTED.
    0600: each channel casts at most one vote.
    Channels: PRICE (best of 1d/5d), THESIS, MACRO, FUNDAMENTALS, AGENT_FINDINGS.
    Trend is not a channel (0592). MULTI_SIGNAL requires 3+ independent channels.
    """
    direction  = event.get("direction", "NEUTRAL")
    event_type = event.get("event_type", "")

    alpha     = _get_price_alpha(ticker, conn)
    th_health = _get_thesis_health(ticker)
    macro_sc  = _get_macro_score(ticker, conn)

    signals: dict       = {}
    corroborating = 0
    contradicting = 0

    # PRICE channel — one vote; use the more extreme of 1d/5d alpha (0600)
    a1d = alpha.get("1d")
    a5d = alpha.get("5d")
    if a1d is not None:
        signals["alpha_1d"] = round(a1d * 100, 2)
    if a5d is not None:
        signals["alpha_5d"] = round(a5d * 100, 2)

    price_alpha: Optional[float] = None
    for a in (a1d, a5d):
        if a is not None and (price_alpha is None or abs(a) > abs(price_alpha)):
            price_alpha = a

    if price_alpha is not None and direction in ("POSITIVE", "NEGATIVE"):
        if direction == "NEGATIVE" and price_alpha < -0.005:
            corroborating += 1
        elif direction == "POSITIVE" and price_alpha > 0.005:
            corroborating += 1
        elif (direction == "NEGATIVE" and price_alpha > 0.01) or \
             (direction == "POSITIVE" and price_alpha < -0.01):
            contradicting += 1

    # THESIS channel (0600)
    if th_health is not None:
        signals["thesis_health"] = round(th_health, 1)
        if direction == "NEGATIVE" and th_health < 50:
            corroborating += 1
        elif direction == "POSITIVE" and th_health > 70:
            corroborating += 1
        elif direction == "NEGATIVE" and th_health > 75:
            contradicting += 1

    # MACRO channel (0600)
    if event_type == "MARGIN" and macro_sc:
        rate_sens = macro_sc.get("rate_sensitivity")
        if rate_sens is not None:
            signals["rate_sensitivity"] = rate_sens
            if direction == "NEGATIVE" and rate_sens >= 7:
                corroborating += 1

    # FUNDAMENTALS channel — one vote (0600 stub)
    fund_trend = _get_fundamentals_trend(ticker, conn)
    if fund_trend is not None:
        signals["fundamentals_trend"] = fund_trend
        if direction == "NEGATIVE" and fund_trend == "negative":
            corroborating += 1
        elif direction == "POSITIVE" and fund_trend == "positive":
            corroborating += 1
        elif direction == "NEGATIVE" and fund_trend == "positive":
            contradicting += 1

    # AGENT_FINDINGS channel — one vote (0600 stub)
    agent_flag = _get_agent_findings_flag(ticker, conn)
    if agent_flag is not None:
        signals["agent_findings"] = agent_flag
        if direction == "NEGATIVE" and agent_flag == "flagged":
            corroborating += 1

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


# ── Portfolio theme detection (0593 causal_driver-based) ─────────────────────

def detect_portfolio_themes(events_by_ticker: dict,
                             portfolio_weights: dict) -> list:
    causal_dir_map: dict = defaultdict(list)

    for ticker, events in events_by_ticker.items():
        seen: set = set()
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
            "event_type":       causal_driver,
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


# ── DB persistence (0596-0599: new fields) ────────────────────────────────────

def persist_events(events_by_ticker: dict,
                   themes: list,
                   day: str,
                   conn: sqlite3.Connection,
                   news_snapshot_hash: str = "",
                   manifest: Optional[dict] = None) -> None:
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

            existing = conn.execute(
                "SELECT first_seen FROM news_events WHERE ticker=? AND event_fingerprint=? "
                "ORDER BY first_seen ASC LIMIT 1",
                (ticker, fingerprint)
            ).fetchone()
            first_seen = existing[0] if existing else day

            article_ids = ev.get("article_ids", [])
            source_count = len(article_ids) if article_ids else 1

            conn.execute(
                """INSERT OR REPLACE INTO news_events
                   (event_id, ticker, day, event_type, direction, magnitude,
                    expected_horizon, confidence, affected_metric, evidence_text,
                    source_titles, source_count, first_seen, last_seen,
                    thesis_relevance, pillar_name, risk_name, catalyst_name,
                    trigger_proximity,
                    pillar_health_state, event_trigger_state, event_trigger_proximity,
                    trend_status, occurrence_count_7d, occurrence_count_30d, occurrence_count_90d,
                    signal_strength, portfolio_priority, score_decomposition,
                    confirmation_class, confirmation_signals, skepticism_note,
                    news_snapshot_hash, extracted_at,
                    event_fingerprint, article_ids_json, causal_driver, causal_event_key,
                    news_intelligence_version)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
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
                    ev.get("pillar_health_state"),
                    ev.get("event_trigger_state", "NONE"),
                    ev.get("event_trigger_proximity", 0.0),
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
                    ev.get("causal_event_key"),
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


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(by_ticker: dict,
                 portfolio_weights: dict,
                 conn: sqlite3.Connection,
                 ollama_client_mod,
                 day=None,
                 snapshot: Optional[dict] = None):
    """
    Run the full news intelligence pipeline.
    0596: accepts optional pre-built snapshot (built after enrichment in portfolio_ai.py).
    Returns dict with: events_by_ticker, themes, news_snapshot_hash, article_count.
    """
    if day is None:
        day = date.today().isoformat()

    # 0596: use canonical snapshot hash; build from by_ticker if not provided
    if snapshot is not None:
        news_snapshot_hash = snapshot["snapshot_hash"]
        # Build manifest from snapshot articles
        manifest = {
            a["article_id"]: {
                "ticker":   a["ticker"],
                "title":    a["title"],
                "source":   a["source"],
                "pub_date": a["published_at"],
                "url":      a["url"],
            }
            for a in snapshot["articles"]
        }
    else:
        snap = build_news_snapshot(by_ticker)
        news_snapshot_hash = snap["snapshot_hash"]
        manifest = None  # built inside extract_events_llm

    article_count = sum(len(v) for v in by_ticker.values())

    extraction_result = extract_events_llm(by_ticker, ollama_client_mod, manifest=manifest)
    manifest = extraction_result.pop("_manifest", manifest or {})
    raw_events = extraction_result
    if not raw_events:
        return {
            "events_by_ticker": {},
            "themes": [],
            "news_snapshot_hash": news_snapshot_hash,
            "article_count": article_count,
        }

    enriched: dict = {}
    for ticker, events in raw_events.items():
        pos_wt = portfolio_weights.get(ticker, 0.0)
        ticker_events = []
        for ev in events:
            thesis_info = map_thesis_relevance(
                ev["event_type"], ticker,
                ev_evidence=ev.get("evidence", ""),
                ev_metric=ev.get("affected_metric", ""),
                ev_direction=ev.get("direction", "NEUTRAL"),
                ollama_client_mod=ollama_client_mod,
            )
            ev.update(thesis_info)

            trend_info = compute_trend(
                ticker, ev["event_type"], ev["direction"], day, conn
            )
            ev.update(trend_info)

            confirm_info = attach_confirmation(ev, ticker, conn)
            ev.update(confirm_info)

            score_info = score_event(ev, position_weight=pos_wt)
            ev.update(score_info)

            ticker_events.append(ev)

        ticker_events.sort(key=lambda e: -e.get("portfolio_priority", 0))
        enriched[ticker] = ticker_events

    themes = detect_portfolio_themes(enriched, portfolio_weights)

    try:
        persist_events(enriched, themes, day, conn, news_snapshot_hash, manifest)
    except Exception as e:
        print(f"[NewsIntelligence] Persist error: {e}")

    # 0598: update news_event_state (no synthetic news_events rows)
    try:
        update_event_state_sweep(day, conn)
    except Exception as e:
        print(f"[NewsIntelligence] Event state sweep error: {e}")

    return {
        "events_by_ticker":  enriched,
        "themes":            themes,
        "news_snapshot_hash": news_snapshot_hash,
        "article_count":    article_count,
        "_manifest":        manifest,
    }


def load_events_for_day(day: str, conn: sqlite3.Connection) -> dict:
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
