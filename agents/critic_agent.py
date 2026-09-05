"""Critic Agent — adversarial review pass for all agent recommendations.

Pipeline:
  1. Query all open recommendations that have no critic_reviews row yet.
  2. Run deterministic vetoes (no LLM) — fast, objective failure modes.
  3. If not vetoed, call LLM for an adversarial critique.
  4. Apply confidence adjustment (bounded [-20, +5]).
  5. Cap confidence at 60 for CHALLENGE verdict.
  6. Set status='vetoed' for VETO (suppresses from Decision Queue).
  7. Write critic_reviews row for every recommendation reviewed.

Returns [] — Critic produces no new recommendations of its own.
"""
import csv
import json
import zoneinfo
from datetime import datetime, timezone
from pathlib import Path

import agent_db
import ollama_client
from strategy_config import LAYER_TARGETS
from .contracts import AgentContext, Recommendation
from .orchestrator import register_agent

# Confidence adjustment bounds
_ADJ_MIN = -20
_ADJ_MAX = 5
# Confidence cap applied when verdict is CHALLENGE
_CHALLENGE_CAP = 60

_PRICE_SENSITIVE_ACTIONS = {"SELL_CC", "BUY", "SELL", "TRIM", "WRITE_CC"}
_TAX_ACTIONS             = {"TAX_SELL", "TAX_HARVEST"}
_ALLOC_ACTIONS           = {"REBALANCE", "ALLOCATE"}

_CRITIC_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["APPROVE", "APPROVE_WITH_CAUTION", "CHALLENGE", "VETO"],
        },
        "strongest_objection": {"type": "string"},
        "missing_evidence":    {"type": "array", "items": {"type": "string"}},
        "counter_case":        {"type": "string"},
        "confidence_adjustment": {"type": "integer"},
    },
    "required": [
        "verdict", "strongest_objection", "missing_evidence",
        "counter_case", "confidence_adjustment",
    ],
}

_SYSTEM = (
    "You are an adversarial investment analyst reviewing a recommendation before it "
    "reaches the user. Your job is to find flaws, missing evidence, and hidden risks. "
    "Be skeptical but fair. VETO only when there is a clear objective reason — do not "
    "VETO merely because you are uncertain. "
    "confidence_adjustment must be an integer in [-20, +5]. "
    "Positive adjustments require strong corroborating evidence."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_market_hours() -> bool:
    """True if current wall-clock time is within NYSE trading hours (M-F 9:30-16:00 ET)."""
    try:
        now_et = datetime.now(tz=zoneinfo.ZoneInfo("America/New_York"))
    except Exception:
        return False
    if now_et.weekday() >= 5:
        return False
    open_  = now_et.replace(hour=9,  minute=30, second=0, microsecond=0)
    close_ = now_et.replace(hour=16, minute=0,  second=0, microsecond=0)
    return open_ <= now_et <= close_


def _payload(rec: dict) -> dict:
    raw = rec.get("action_payload_json")
    if not raw:
        return {}
    try:
        return json.loads(raw) or {}
    except Exception:
        return {}


def _holding_current_price(ticker: str) -> float | None:
    """Return the most recent price for ticker from holding_day, or None."""
    try:
        conn = agent_db._connect()
        row = conn.execute(
            "SELECT price FROM holding_day WHERE ticker=? ORDER BY day DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        conn.close()
        return float(row["price"]) if row else None
    except Exception:
        return None


def _holdings_avg_cost(ticker: str) -> float | None:
    """Return avg cost per share from holdings.csv for ticker, or None if not found."""
    holdings_csv = Path(agent_db.DB_PATH).parent.parent / "holdings.csv"
    if not holdings_csv.exists():
        return None
    try:
        with open(holdings_csv) as f:
            for row in csv.DictReader(f):
                if row.get("Stock", "").strip().upper() == ticker.upper():
                    raw = row.get("AvgCost", "").strip()
                    return float(raw) if raw else None
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Deterministic vetoes (no LLM)
# ---------------------------------------------------------------------------

def _deterministic_veto(rec: dict) -> tuple[bool, str]:
    """Return (is_vetoed, reason_string). No LLM call."""
    action  = rec.get("action", "")
    payload = _payload(rec)
    ticker  = rec.get("ticker", "")

    # Veto 1: AVOID-level event risk on a CC recommendation
    if action == "SELL_CC" and payload.get("has_avoid"):
        return True, "AVOID-level event risk present for this covered call contract"

    # Veto 2: Layer targets invalid for allocation recommendations
    if action in _ALLOC_ACTIONS:
        target_sum = sum(LAYER_TARGETS.values())
        if abs(target_sum - 100) > 0.5:
            return True, (
                f"Layer targets sum to {target_sum:.1f}% — "
                "allocation recommendation invalid until targets are corrected"
            )

    # Veto 3: Missing cost basis for tax-specific recommendations
    if action in _TAX_ACTIONS:
        conn = agent_db._connect()
        has_lots = conn.execute(
            "SELECT 1 FROM cost_lots WHERE ticker=? LIMIT 1", (ticker,)
        ).fetchone()
        conn.close()
        if not has_lots:
            return True, (
                f"No cost-basis lots found for {ticker} — "
                "tax recommendation cannot be evaluated without cost basis"
            )

    # Veto 4: Theoretical option pricing for actionable CC trade
    if action == "SELL_CC" and payload.get("data_mode") == "theoretical":
        return True, (
            "Option pricing is theoretical (no live market quote) — "
            "trade is not immediately actionable"
        )

    # Veto 5a: CC strike is ITM (below current price) — near-certain assignment
    if action == "SELL_CC":
        strike = payload.get("strike")
        if strike is not None:
            current_price = _holding_current_price(ticker)
            if current_price is not None and float(strike) < current_price:
                return True, (
                    f"Strike ${strike} is below the current price of ${current_price:.2f} "
                    f"(delta {payload.get('delta', '?')}) — ITM call has near-certain assignment risk"
                )

    # Veto 5b: CC strike below cost basis — guaranteed loss if assigned
    if action == "SELL_CC":
        strike = payload.get("strike")
        if strike is not None:
            avg_cost = _holdings_avg_cost(ticker)
            if avg_cost is not None and float(strike) < avg_cost:
                return True, (
                    f"Strike ${strike} is below your cost basis of ${avg_cost:.2f} — "
                    "assignment would lock in a realized loss on this position"
                )

    # Veto 5: Stale price data during market hours
    if action in _PRICE_SENSITIVE_ACTIONS and _is_market_hours():
        conn = agent_db._connect()
        latest_day = conn.execute(
            "SELECT MAX(day) FROM holding_day WHERE ticker=?", (ticker,)
        ).fetchone()[0]
        conn.close()
        today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        if latest_day and latest_day < today:
            return True, (
                f"Price data for {ticker} is from {latest_day} — "
                "stale during market hours, recommendation not actionable"
            )

    return False, ""


# ---------------------------------------------------------------------------
# LLM critique
# ---------------------------------------------------------------------------

def _llm_critique(rec: dict) -> dict | None:
    action  = rec.get("action", "")
    ticker  = rec.get("ticker", "UNKNOWN")
    payload = _payload(rec)

    prompt = (
        f"{_SYSTEM}\n\n"
        f"Recommendation to review:\n"
        f"  Ticker:  {ticker}\n"
        f"  Action:  {action}\n"
        f"  Score:   {rec.get('recommendation_score', '?')}/100\n"
        f"  Confidence (pre-critic): {rec.get('confidence', '?')}\n"
        f"  Why now: {rec.get('why_now') or '(none)'}\n"
        f"  Rationale: {rec.get('rationale') or '(none)'}\n"
        f"  Counter case: {rec.get('counter_case') or '(none)'}\n"
    )
    if payload:
        payload_summary = {k: v for k, v in payload.items()
                           if k in ("data_mode", "dte", "strike", "exec_premium",
                                    "cc_alpha", "regret_prob", "delta", "has_caution",
                                    "hv_rank", "atm_iv", "score")}
        if payload_summary:
            prompt += f"  Key payload fields: {json.dumps(payload_summary)}\n"

    prompt += (
        "\nReturn JSON matching the schema exactly. "
        "confidence_adjustment must be an integer in [-20, +5]. "
        "strongest_objection: the single most important concern (1 sentence). "
        "missing_evidence: list of facts that would change the verdict. "
        "counter_case: best argument against acting on this recommendation."
    )

    try:
        out = ollama_client.generate_structured(
            prompt=prompt,
            schema=_CRITIC_SCHEMA,
            model="mlx-community/Qwen3.6-35B-A3B-4bit",
            temperature=0.3,
            num_predict=700,
            thinking=False,
            retries=2,
        )
        if not isinstance(out, dict):
            return None
        if out.get("verdict") not in {"APPROVE", "APPROVE_WITH_CAUTION", "CHALLENGE", "VETO"}:
            return None
        # Clamp confidence_adjustment
        adj = int(out.get("confidence_adjustment", 0))
        out["confidence_adjustment"] = max(_ADJ_MIN, min(_ADJ_MAX, adj))
        return out
    except Exception as e:
        print(f"[critic] LLM call failed for {ticker}/{action}: {e}")
        return None


# ---------------------------------------------------------------------------
# Main agent entry point
# ---------------------------------------------------------------------------

def run_critic_agent(ctx: AgentContext) -> list[Recommendation]:
    recs = agent_db.list_open_unreviewed_recommendations()
    if not recs:
        print("[critic] No unreviewed open recommendations — nothing to do")
        return []

    print(f"[critic] Reviewing {len(recs)} recommendation(s)")

    for rec in recs:
        rec_id  = rec["id"]
        ticker  = rec.get("ticker", "?")
        action  = rec.get("action", "?")
        orig_conf = rec.get("confidence", 50)

        # ── Deterministic gate ────────────────────────────────────────────
        vetoed, veto_reason = _deterministic_veto(rec)
        if vetoed:
            print(f"[critic] VETO (deterministic) {ticker}/{action}: {veto_reason}")
            agent_db.insert_critic_review(
                recommendation_id=rec_id,
                verdict="VETO",
                strongest_objection=veto_reason,
                missing_evidence=[],
                confidence_adjustment=0,
            )
            agent_db.update_recommendation(rec_id, status="vetoed")
            continue

        # ── LLM critique ──────────────────────────────────────────────────
        llm = _llm_critique(rec)

        if llm is None:
            # LLM failed — approve cautiously so rec isn't silently dropped
            print(f"[critic] LLM failed for {ticker}/{action} — defaulting APPROVE_WITH_CAUTION")
            llm = {
                "verdict": "APPROVE_WITH_CAUTION",
                "strongest_objection": "Critic LLM unavailable — review manually.",
                "missing_evidence": [],
                "counter_case": "(LLM unavailable)",
                "confidence_adjustment": -5,
            }

        verdict = llm["verdict"]
        adj     = llm["confidence_adjustment"]
        new_conf = max(0, min(100, orig_conf + adj))

        if verdict == "CHALLENGE":
            new_conf = min(new_conf, _CHALLENGE_CAP)

        print(f"[critic] {ticker}/{action}: verdict={verdict} "
              f"conf {orig_conf}→{new_conf} (adj={adj:+d})")

        # Write critic review
        agent_db.insert_critic_review(
            recommendation_id=rec_id,
            verdict=verdict,
            strongest_objection=llm.get("strongest_objection"),
            missing_evidence=llm.get("missing_evidence", []),
            confidence_adjustment=adj,
        )

        # Apply confidence update (and veto if LLM said so)
        if verdict == "VETO":
            agent_db.update_recommendation(rec_id, confidence=new_conf, status="vetoed")
        else:
            agent_db.update_recommendation(rec_id, confidence=new_conf)

    return []


register_agent("critic", run_critic_agent)
