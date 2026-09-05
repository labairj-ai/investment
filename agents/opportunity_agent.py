"""Opportunity Hunter Agent (Phase 6).

Reads Buffett screener winners, scores each for portfolio fit, and
surfaces the top candidate as a RESEARCH recommendation.

Score = 0.30*Q + 0.25*V + 0.20*PF + 0.15*C + 0.10*EC  (all 0-100)
  Q  — Quality (buffett_winners.quality_score)
  V  — Valuation (pe_ratio, p_fcf, ev_ebitda — lower is better)
  PF — Portfolio Fit (layer deficit bonus + sector overlap penalty)
  C  — Catalyst/Setup (value-trap risk, AI conviction, scan freshness)
  EC — Evidence Confidence (from confidence.py)
"""
import csv
import json
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import agent_db
import ollama_client
from strategy_config import LAYER_NAMES, LAYER_TARGETS, LAYER_LABELS

from .confidence import calculate_confidence
from .contracts import AgentContext, EvidenceBundle, Recommendation
from .orchestrator import register_agent

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BUFFETT_DB = Path(agent_db.DB_PATH).parent / "buffett.db"
_MAX_CANDIDATES = 3          # candidates passed to the LLM
_LAYER_DEFICIT_THRESHOLD = 5.0  # pp underweight before PF bonus kicks in

# Sector labels for current holdings.
# ETFs / broad funds → None (excluded from sector overlap penalty).
# Update when holdings change — unknown tickers default to None (no penalty).
_HOLDING_SECTORS: dict[str, str | None] = {
    "BRK-B":  "Financial Services",
    "TROW":   "Financial Services",
    "VLY":    "Financial Services",
    "MCO":    "Financial Services",
    "BP":     "Energy",
    "GRMN":   "Technology",
    "DSGX":   "Technology",
    "NFLX":   "Communication Services",
    "EW":     "Healthcare",
    "ITW":    "Industrials",
    "SNA":    "Industrials",
    "NOC":    "Industrials",
    "UNP":    "Industrials",
    "MITSF":  "Industrials",
    "ITOCF":  "Industrials",
    "WMT":    "Consumer Defensive",
    "STZ":    "Consumer Defensive",
    "JOBY":   "Industrials",
    # Broad funds — no sector overlap
    "SCHD": None, "VFIAX": None, "VTSAX": None, "VTMGX": None,
    "VVIAX": None, "FSPTX": None, "SLYV": None, "IGV": None,
    "BTC": None,
}

_LLM_SCHEMA = {
    "action": "",
    "ticker": "",
    "why": "",
    "portfolio_rationale": "",
    "main_risk": "",
    "no_action_case": "",
}


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def _get_buffett_winners() -> list[dict]:
    if not _BUFFETT_DB.exists():
        print(f"[opportunity] buffett.db not found at {_BUFFETT_DB}")
        return []
    conn = sqlite3.connect(str(_BUFFETT_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM buffett_winners ORDER BY scanned_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _get_current_tickers() -> set[str]:
    holdings_csv = Path(agent_db.DB_PATH).parent.parent / "holdings.csv"
    if not holdings_csv.exists():
        return set()
    with open(holdings_csv) as f:
        return {row["Stock"].strip().upper() for row in csv.DictReader(f) if row.get("Stock")}


def _get_layer_weights() -> dict[int, float]:
    """Return {layer_num: weight_pct} from most recent layer_day."""
    conn = agent_db._connect()
    day = conn.execute("SELECT MAX(day) FROM layer_day").fetchone()[0]
    if not day:
        conn.close()
        return {}
    rows = conn.execute(
        "SELECT layer, weight_pct FROM layer_day WHERE day=?", (day,)
    ).fetchall()
    conn.close()
    label_to_int = {v: k for k, v in LAYER_LABELS.items()}
    return {label_to_int[r["layer"]]: r["weight_pct"] for r in rows if r["layer"] in label_to_int}


# ---------------------------------------------------------------------------
# Scoring components (all return 0-100)
# ---------------------------------------------------------------------------

def _score_quality(w: dict) -> float:
    q = w.get("quality_score")
    return float(q) if q is not None else 50.0


def _score_valuation(w: dict) -> float:
    def _pe(v):
        if v is None: return 50.0
        if v <= 18:   return 100.0
        if v <= 25:   return 80.0
        if v <= 35:   return 60.0
        return 30.0

    def _pfcf(v):
        if v is None: return 40.0
        if v <= 15:   return 100.0
        if v <= 25:   return 80.0
        if v <= 35:   return 60.0
        return 25.0

    def _ev(v):
        if v is None: return 40.0
        if v <= 12:   return 100.0
        if v <= 18:   return 75.0
        if v <= 25:   return 55.0
        return 25.0

    samples = [_pe(w.get("pe_ratio")), _pfcf(w.get("p_fcf")), _ev(w.get("ev_ebitda"))]
    return sum(samples) / len(samples)


def _score_portfolio_fit(
    w: dict, held: set[str], layer_weights: dict[int, float]
) -> tuple[float, dict]:
    """Returns (score 0-100, metadata dict for rationale)."""
    score = 50.0
    meta: dict = {}

    if w["ticker"] in held:
        return 0.0, {"reason": "already held"}

    # Layer deficit bonus
    layer_rec = w.get("layer_rec")
    if layer_rec and layer_rec in LAYER_TARGETS:
        target = LAYER_TARGETS[layer_rec]
        actual = layer_weights.get(layer_rec, target)
        deficit = target - actual  # positive = underweight
        meta["layer_rec"] = layer_rec
        meta["layer_name"] = LAYER_NAMES.get(layer_rec, f"L{layer_rec}")
        meta["layer_deficit_pp"] = round(deficit, 1)
        if deficit >= _LAYER_DEFICIT_THRESHOLD:
            bonus = min(30.0, deficit * 4)  # 5pp→+20, 7.5pp→+30
            score += bonus

    # Sector overlap penalty (≥2 existing holdings in same sector)
    sector = w.get("sector") or ""
    if sector:
        overlap = sum(
            1 for t in held
            if _HOLDING_SECTORS.get(t) == sector
        )
        if overlap >= 2:
            penalty = min(30.0, (overlap - 1) * 10)
            score -= penalty
            meta["sector_overlap"] = overlap
        meta["sector"] = sector

    return max(0.0, min(100.0, score)), meta


def _score_catalyst(w: dict) -> float:
    score = 50.0

    trap = (w.get("value_trap_risk") or "").lower()
    if trap == "low":
        score += 15.0
    elif trap == "high":
        score -= 20.0

    ai_raw = w.get("ai_analysis")
    if ai_raw:
        try:
            ai = json.loads(ai_raw) if isinstance(ai_raw, str) else ai_raw
            conviction = ai.get("conviction", 0)
            if conviction >= 4:
                score += 15.0
            elif conviction >= 3:
                score += 5.0
        except (json.JSONDecodeError, TypeError):
            pass

    scanned = w.get("scanned_at")
    if scanned:
        try:
            age_days = (datetime.now() - datetime.fromisoformat(scanned)).days
            if age_days <= 7:
                score += 10.0
            elif age_days <= 30:
                score += 5.0
        except ValueError:
            pass

    return max(0.0, min(100.0, score))


def _score_evidence(w: dict) -> float:
    b = EvidenceBundle(
        has_price=w.get("price") is not None,
        financial_quarters=4 if w.get("last_quarter_date") else 0,
        has_strategy_metadata=bool(w.get("ai_analysis")),
        source_quality="primary_release",
        rule_support=0.8,  # passed deterministic Buffett filter
    )
    scanned = w.get("scanned_at")
    if scanned:
        try:
            b.macro_class_age_days = float(
                (datetime.now() - datetime.fromisoformat(scanned)).days
            )
        except ValueError:
            pass
    return float(calculate_confidence(b))


def _composite(q: float, v: float, pf: float, c: float, ec: float) -> int:
    return round(0.30 * q + 0.25 * v + 0.20 * pf + 0.15 * c + 0.10 * ec)


# ---------------------------------------------------------------------------
# LLM selection
# ---------------------------------------------------------------------------

_SYSTEM = (
    "You are a portfolio research analyst. You receive data on Buffett-quality "
    "stock candidates scored for portfolio fit. Select the single best candidate "
    "for further research and explain the portfolio rationale. "
    "action must always be exactly RESEARCH. Do not recommend buying or selling."
)


def _llm_select(candidates: list[dict], layer_weights: dict[int, float]) -> dict | None:
    layer_lines = []
    for n, w in sorted(layer_weights.items()):
        t = LAYER_TARGETS.get(n, 0)
        deficit = t - w
        status = ("UNDERWEIGHT" if deficit > 2 else
                  "OVERWEIGHT" if deficit < -2 else "on target")
        layer_lines.append(
            f"  Layer {n} ({LAYER_NAMES.get(n,'?')}): "
            f"{w:.1f}% actual vs {t:.0f}% target — {status} by {abs(deficit):.1f}pp"
        )

    cand_lines = []
    for i, c in enumerate(candidates, 1):
        ai_thesis = ""
        ai_raw = c.get("ai_analysis")
        if ai_raw:
            try:
                ai = json.loads(ai_raw) if isinstance(ai_raw, str) else ai_raw
                ai_thesis = (ai.get("thesis") or "")[:200]
            except (json.JSONDecodeError, TypeError):
                pass
        meta = c.get("_pf_meta", {})
        cand_lines.append(
            f"  [{i}] {c['ticker']} ({c.get('company', '')})  "
            f"composite={c['_composite']} | "
            f"layer_rec={c.get('layer_rec')} ({meta.get('layer_name','?')}) "
            f"deficit={meta.get('layer_deficit_pp', 0):+.1f}pp | "
            f"sector={c.get('sector','')} | "
            f"quality={c.get('quality_score')} "
            f"PE={c.get('pe_ratio')} P/FCF={c.get('p_fcf')} EV/EBITDA={c.get('ev_ebitda')} "
            f"trap={c.get('value_trap_risk')} | "
            f"thesis: {ai_thesis}"
        )

    prompt = (
        f"{_SYSTEM}\n\n"
        f"CURRENT LAYER WEIGHTS:\n" + "\n".join(layer_lines) + "\n\n"
        f"TOP CANDIDATES:\n" + "\n".join(cand_lines) + "\n\n"
        "Select the single best candidate for RESEARCH. Explain why it improves this "
        "specific portfolio (cite the layer it fills, sector diversification, or "
        "quality/valuation edge). Return JSON:\n"
        '{"action":"RESEARCH","ticker":"<TICKER>",'
        '"why":"<1-2 sentences why it fits now>",'
        '"portfolio_rationale":"<2-3 sentences on portfolio-level benefit>",'
        '"main_risk":"<top risk to this thesis, 1-2 sentences>",'
        '"no_action_case":"<strongest reason to skip research now, 1 sentence>"}'
    )
    try:
        out = ollama_client.generate_structured(
            prompt=prompt,
            schema=_LLM_SCHEMA,
            model="mlx-community/Qwen3.6-35B-A3B-4bit",
            temperature=0.2,
            num_predict=800,
            thinking=False,
            retries=2,
        )
        if isinstance(out, dict) and out.get("action") == "RESEARCH" and out.get("ticker"):
            return out
        print(f"[opportunity] LLM returned invalid schema: {out}")
    except Exception as e:
        print(f"[opportunity] LLM failed: {e}")
    return None


def _fallback_select(candidates: list[dict]) -> dict:
    best = candidates[0]
    meta = best.get("_pf_meta", {})
    layer_name = meta.get("layer_name", "?")
    deficit = meta.get("layer_deficit_pp", 0.0)
    direction = "underweight" if deficit > 0 else "overweight"
    return {
        "action": "RESEARCH",
        "ticker": best["ticker"],
        "why": (
            f"{best['ticker']} is the top-ranked Buffett screener candidate "
            f"(composite score {best['_composite']})."
        ),
        "portfolio_rationale": (
            f"Recommended for Layer {best.get('layer_rec')} ({layer_name}), "
            f"currently {abs(deficit):.1f}pp {direction}. "
            f"Sector: {best.get('sector', 'unknown')}. "
            f"Quality score: {best.get('quality_score', '?')}."
        ),
        "main_risk": f"Value trap risk rated '{best.get('value_trap_risk', 'unknown')}'.",
        "no_action_case": (
            "LLM unavailable — candidate selected deterministically; "
            "manual review recommended before acting."
        ),
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_opportunity_hunter(ctx: AgentContext) -> list[Recommendation]:
    print("[opportunity] Starting Opportunity Hunter sweep")

    winners = _get_buffett_winners()
    if not winners:
        print("[opportunity] No Buffett winners in DB — no recommendation")
        return []

    held = _get_current_tickers()
    layer_weights = _get_layer_weights()

    # Score every unowned winner
    scored: list[dict] = []
    for w in winners:
        if w["ticker"] in held:
            continue
        q  = _score_quality(w)
        v  = _score_valuation(w)
        pf, pf_meta = _score_portfolio_fit(w, held, layer_weights)
        c  = _score_catalyst(w)
        ec = _score_evidence(w)
        w = dict(w)
        w["_q"]       = q
        w["_v"]       = v
        w["_pf"]      = pf
        w["_pf_meta"] = pf_meta
        w["_c"]       = c
        w["_ec"]      = ec
        w["_composite"] = _composite(q, v, pf, c, ec)
        scored.append(w)

    if not scored:
        print("[opportunity] All Buffett winners are already held — no recommendation")
        return []

    scored.sort(key=lambda x: x["_composite"], reverse=True)
    top = scored[:_MAX_CANDIDATES]

    print(
        f"[opportunity] {len(scored)} unowned candidates scored; "
        f"top {len(top)}: " + ", ".join(f"{c['ticker']}={c['_composite']}" for c in top)
    )

    # LLM selects the best among top candidates
    llm = _llm_select(top, layer_weights)
    if llm:
        selected_ticker = llm["ticker"].upper().strip()
        selected = next((c for c in top if c["ticker"] == selected_ticker), top[0])
        result = llm
    else:
        result = _fallback_select(top)
        selected = top[0]

    # Assemble recommendation
    meta = selected.get("_pf_meta", {})
    layer_rec   = selected.get("layer_rec")
    layer_name  = meta.get("layer_name", LAYER_NAMES.get(layer_rec, "?"))
    layer_deficit = meta.get("layer_deficit_pp", 0.0)

    action_payload = {
        "candidates": [
            {
                "ticker":          c["ticker"],
                "company":         c.get("company"),
                "composite_score": c["_composite"],
                "layer_rec":       c.get("layer_rec"),
                "sector":          c.get("sector"),
                "quality_score":   c.get("quality_score"),
                "pe_ratio":        c.get("pe_ratio"),
                "p_fcf":           c.get("p_fcf"),
                "ev_ebitda":       c.get("ev_ebitda"),
                "value_trap_risk": c.get("value_trap_risk"),
            }
            for c in top
        ],
        "selected_ticker":  selected["ticker"],
        "layer_fill":       layer_rec,
        "layer_name":       layer_name,
        "layer_deficit_pp": round(layer_deficit, 1),
        "sector":           selected.get("sector"),
    }

    confidence = calculate_confidence(EvidenceBundle(
        has_price=True,
        financial_quarters=4,
        has_strategy_metadata=bool(selected.get("ai_analysis")),
        source_quality="primary_release",
        rule_support=0.8,
        has_recent_fundamentals=True,
    ))

    rec = Recommendation(
        ticker=selected["ticker"],
        action="RESEARCH",
        recommendation_score=selected["_composite"],
        confidence=confidence,
        priority="normal",
        why_now=result.get("why"),
        rationale=result.get("portfolio_rationale"),
        counter_case=result.get("main_risk"),
        no_action_case=result.get("no_action_case"),
        action_payload=action_payload,
        valid_until=time.time() + 7 * 86400,
    )

    print(
        f"[opportunity] → RESEARCH {selected['ticker']} "
        f"(score={selected['_composite']}, "
        f"layer={layer_rec} {layer_name}, "
        f"deficit={layer_deficit:+.1f}pp)"
    )
    return [rec]


register_agent("opportunity_hunter", run_opportunity_hunter)
