"""Sell/Trim Agent — evaluates every held position on a disposition framework.

SellStrength = 0.40*T + 0.20*F + 0.15*V + 0.15*P + 0.10*O

All five components are computed deterministically from DB reads before any
LLM call. The LLM receives the scores and writes rationale; it never invents
them. Price movement is not a component — the agent is gated by trigger_type
(portfolio_scope), so a price move alone cannot produce a sell recommendation.

Tax friction is computed separately and stored in action_payload; it does not
modify SellStrength.
"""

import datetime
import json
import sqlite3
from pathlib import Path

import agent_db
from agent_db import CAND_OPPORTUNITY_STATUSES
import ollama_client
from agents.confidence import calculate_confidence as score_evidence
from agents.contracts import AgentContext, EvidenceBundle, Recommendation
from agents.orchestrator import register_agent

_DB = Path(__file__).resolve().parent.parent / "out" / "investment.db"

_RATIONALE_CLASSES = frozenset({
    "THESIS_BREAK", "FUNDAMENTAL_DETERIORATION", "VALUATION",
    "PORTFOLIO_CONCENTRATION", "CAPITAL_REALLOCATION", "RISK_CHANGE", "TAX_STRATEGY",
})

_NO_ACTION_THRESHOLD = 10   # ss below this → upsert_no_action, skip LLM

_DEFAULT_MAX_WEIGHT_PCT = 10.0   # used when thesis has no max_weight_pct set


def _connect() -> sqlite3.Connection | None:
    if not _DB.exists():
        return None
    conn = sqlite3.connect(str(_DB), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


# ── Action from SellStrength ──────────────────────────────────────────────────

def _action_from_strength(ss: float) -> str:
    if ss < _NO_ACTION_THRESHOLD:
        return "NO_ACTION"
    if ss < 28:
        return "HOLD"
    if ss < 48:
        return "REVIEW"
    if ss < 68:
        return "TRIM"
    return "EXIT"


def _dominant_rationale(T: int, F: int, V: int, P: int, O: int) -> str:
    """Return rationale class for the highest-weighted component."""
    weighted = [
        (0.40 * T, "THESIS_BREAK"),
        (0.20 * F, "FUNDAMENTAL_DETERIORATION"),
        (0.15 * V, "VALUATION"),
        (0.15 * P, "PORTFOLIO_CONCENTRATION"),
        (0.10 * O, "CAPITAL_REALLOCATION"),
    ]
    return max(weighted, key=lambda x: x[0])[1]


# ── Component scorers (all deterministic, no LLM) ────────────────────────────

_PILLAR_STATUS_SCORE: dict[str, float] = {
    "STRONG":   95.0,
    "HEALTHY":  80.0,
    "WATCH":    65.0,
    "WARNING":  40.0,
    "VIOLATED": 10.0,
    "UNKNOWN":  50.0,
}


def _score_T(ticker: str) -> tuple[int, list[dict]]:
    """T = thesis deterioration (0–100). 40% weight in SellStrength.

    Reads thesis_pillars (modern system). Falls back to thesis_claims only
    when no pillar rows exist, so legacy data still contributes a signal.
    T-score matches the composite health the Thesis Monitor would report.
    """
    conn = _connect()
    if not conn:
        return 0, []

    # ── Modern path: thesis_pillars ────────────────────────────────────────
    pillars = conn.execute(
        """SELECT tp.name, tp.status, tp.score, tp.importance, tp.critical
           FROM thesis_pillars tp
           JOIN investment_theses it ON it.id = tp.thesis_id
           WHERE it.ticker = ? AND it.status = 'ACTIVE'
           ORDER BY tp.importance DESC""",
        (ticker,),
    ).fetchall()

    if pillars:
        conn.close()
        total_w = sum(p["importance"] for p in pillars) or 1.0
        composite = sum(
            p["importance"] * (
                p["score"] if p["score"] is not None
                else _PILLAR_STATUS_SCORE.get(p["status"], 50.0)
            )
            for p in pillars
        ) / total_w

        T = max(0, min(100, round(100 - composite)))

        critical_violated = [p for p in pillars if p["critical"] and p["status"] == "VIOLATED"]
        all_violated      = [p for p in pillars if p["status"] == "VIOLATED"]
        any_warning       = any(p["status"] in ("WARNING", "WATCH") for p in pillars)

        if critical_violated:
            T = max(T, 90)
        elif len(all_violated) >= 2:
            T = max(T, 75)
        elif any_warning and not all_violated:
            T = min(T, 50)

        detail = [
            {"claim": p["name"], "status": p["status"], "weight": p["importance"]}
            for p in pillars if p["status"] in ("VIOLATED", "WARNING", "WATCH")
        ]
        return T, detail

    # ── Legacy fallback: thesis_claims ─────────────────────────────────────
    rows = conn.execute(
        """SELECT tc.claim, tc.claim_type, tc.weight, tc.current_status
           FROM thesis_claims tc
           JOIN investment_theses it ON it.id = tc.thesis_id
           WHERE it.ticker = ? AND it.status = 'ACTIVE'""",
        (ticker,),
    ).fetchall()
    conn.close()
    if not rows:
        return 0, []
    violated = [r for r in rows if r["current_status"] == "violated"]
    weakened = [r for r in rows if r["current_status"] == "weakened"]
    total_w  = sum(r["weight"] for r in rows) or 1.0
    viol_w   = sum(r["weight"] for r in violated)
    weak_w   = sum(r["weight"] for r in weakened)
    score    = min(100, int((viol_w * 1.0 + weak_w * 0.4) / total_w * 100))
    detail   = [
        {"claim": r["claim"], "status": r["current_status"], "weight": r["weight"]}
        for r in violated + weakened
    ]
    return score, detail


def _score_F(ticker: str, current_price: float) -> tuple[int, str]:
    """F = fundamental deterioration (0–100). 20% weight."""
    conn = _connect()
    if not conn:
        return 0, "no data"
    quarters = conn.execute(
        """SELECT revenue, gross_profit, operating_income, free_cash_flow,
                  eps_diluted, period_end
           FROM company_financials
           WHERE ticker = ? AND period_type = 'Q'
           ORDER BY period_end DESC LIMIT 4""",
        (ticker,),
    ).fetchall()
    est = conn.execute(
        "SELECT price_target FROM company_estimates "
        "WHERE ticker = ? ORDER BY fetched_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    conn.close()

    if not quarters:
        return 0, "no financials"

    score = 0
    notes: list[str] = []
    newest = quarters[0]
    oldest = quarters[-1]

    # Revenue trend (newest vs oldest available quarter)
    if oldest["revenue"] and abs(oldest["revenue"]) > 0:
        rev_chg = (newest["revenue"] - oldest["revenue"]) / abs(oldest["revenue"])
        if rev_chg < -0.05:
            score += 35
            notes.append(f"revenue {rev_chg*100:.0f}%")
        elif rev_chg < 0:
            score += 15
            notes.append("revenue flat/declining")

    # Gross margin trend
    if (oldest["gross_profit"] and oldest["revenue"]
            and newest["gross_profit"] and newest["revenue"]):
        gm_old = oldest["gross_profit"] / oldest["revenue"]
        gm_new = newest["gross_profit"] / newest["revenue"]
        diff   = gm_new - gm_old
        if diff < -0.03:
            score += 30
            notes.append(f"margin {diff*100:.1f}pp")
        elif diff < 0:
            score += 10
            notes.append("slight margin erosion")

    # Free cash flow
    if newest["free_cash_flow"] is not None and newest["free_cash_flow"] < 0:
        score += 15
        notes.append("negative FCF")

    # Analyst price target vs current price
    if est and est["price_target"] and current_price > 0:
        upside = (est["price_target"] - current_price) / current_price
        if upside < -0.15:
            score += 15
            notes.append(f"PT {upside*100:.0f}% below price")

    return min(100, score), "; ".join(notes) or "no material deterioration"


def _score_V(ticker: str, current_price: float) -> tuple[int, str]:
    """V = valuation risk (0–100). 15% weight."""
    if current_price <= 0:
        return 25, "no price"
    conn = _connect()
    if not conn:
        return 25, "no data"
    est = conn.execute(
        "SELECT price_target FROM company_estimates "
        "WHERE ticker = ? ORDER BY fetched_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    conn.close()
    if not est or not est["price_target"]:
        return 25, "no analyst price target"
    pt = est["price_target"]
    upside = (pt - current_price) / current_price
    if upside < -0.20:
        return 85, f"PT ${pt:.0f} is {abs(upside)*100:.0f}% below current"
    if upside < -0.10:
        return 60, f"PT ${pt:.0f} is {abs(upside)*100:.0f}% below current"
    if upside < -0.03:
        return 35, f"PT ${pt:.0f} slightly below current"
    if upside < 0.05:
        return 20, f"PT ${pt:.0f} near current"
    return 10, f"PT ${pt:.0f} ({upside*100:.0f}% upside)"


def _score_P(ticker: str, weight_pct: float) -> tuple[int, str]:
    """P = portfolio concentration risk (0–100). 15% weight."""
    conn = _connect()
    max_w = _DEFAULT_MAX_WEIGHT_PCT
    if conn:
        row = conn.execute(
            "SELECT max_weight_pct FROM investment_theses "
            "WHERE ticker = ? AND status = 'ACTIVE' ORDER BY version DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if row and row["max_weight_pct"]:
            max_w = row["max_weight_pct"]
        conn.close()
    if max_w <= 0:
        max_w = _DEFAULT_MAX_WEIGHT_PCT
    excess = weight_pct / max_w
    if excess >= 2.5:
        return 90, f"{weight_pct:.1f}% actual vs {max_w:.1f}% max ({excess:.1f}x)"
    if excess >= 2.0:
        return 75, f"{weight_pct:.1f}% actual vs {max_w:.1f}% max ({excess:.1f}x)"
    if excess >= 1.5:
        return 55, f"{weight_pct:.1f}% actual vs {max_w:.1f}% max ({excess:.1f}x)"
    if excess >= 1.2:
        return 35, f"{weight_pct:.1f}% actual vs {max_w:.1f}% max ({excess:.1f}x)"
    if excess >= 1.0:
        return 15, f"{weight_pct:.1f}% at max {max_w:.1f}%"
    return 0, f"{weight_pct:.1f}% under max {max_w:.1f}%"


def _score_O(ticker: str) -> tuple[int, str]:
    """O = opportunity cost (0–100). 10% weight."""
    conn = _connect()
    if not conn:
        return 10, "no data"
    placeholders = ",".join("?" for _ in CAND_OPPORTUNITY_STATUSES)
    candidates = conn.execute(
        f"SELECT ticker, buffett_score FROM candidate_universe "
        f"WHERE status IN ({placeholders}) ORDER BY buffett_score DESC LIMIT 5",
        CAND_OPPORTUNITY_STATUSES,
    ).fetchall()
    holding_row = conn.execute(
        "SELECT buffett_score FROM candidate_universe WHERE ticker = ?", (ticker,)
    ).fetchone()
    conn.close()
    if not candidates:
        return 10, "no candidates in universe"
    max_cand = max((c["buffett_score"] or 0) for c in candidates)
    top_ticker = next((c["ticker"] for c in candidates), "?")
    h_score = (holding_row["buffett_score"] if holding_row and holding_row["buffett_score"] else 50)
    gap = max_cand - h_score
    if gap >= 30:
        return 65, f"top candidate {top_ticker} scores {max_cand} vs holding {h_score}"
    if gap >= 15:
        return 40, f"moderate gap: {top_ticker}={max_cand}"
    if gap >= 5:
        return 20, "small opportunity gap"
    return 5, "no better alternatives in candidate universe"


# ── Tax calculation (separate from SellStrength) ─────────────────────────────

def _tax_note(ticker: str, current_price: float) -> str:
    """Estimate tax friction on full exit. Never feeds into SellStrength."""
    if current_price <= 0:
        return "no price data"
    conn = _connect()
    if not conn:
        return "no lot data"
    lots = conn.execute(
        "SELECT shares, cost_per_share, purchase_date FROM cost_lots WHERE ticker = ?",
        (ticker,),
    ).fetchall()
    conn.close()
    if not lots:
        return "no lots on record"
    today = datetime.date.today()
    total_gain = 0.0
    total_tax  = 0.0
    lt_shares  = 0.0
    st_shares  = 0.0
    for lot in lots:
        try:
            pd = datetime.date.fromisoformat(lot["purchase_date"])
        except (ValueError, TypeError):
            continue
        days   = (today - pd).days
        is_lt  = days >= 365
        gain   = (current_price - lot["cost_per_share"]) * lot["shares"]
        rate   = 0.15 if is_lt else 0.37
        tax    = max(0.0, gain * rate)
        total_gain += gain
        total_tax  += tax
        if is_lt:
            lt_shares += lot["shares"]
        else:
            st_shares += lot["shares"]
    parts = []
    if lt_shares:
        parts.append(f"{lt_shares:.0f} LT sh")
    if st_shares:
        parts.append(f"{st_shares:.0f} ST sh")
    share_note = ", ".join(parts)
    return (
        f"Est. tax on full exit: ${total_tax:,.0f} "
        f"({share_note}); net gain after tax ${total_gain - total_tax:,.0f}"
    )


# ── LLM rationale call ────────────────────────────────────────────────────────

def _call_llm(
    ticker: str,
    ss: float,
    T: int, F: int, V: int, P: int, O: int,
    t_detail: list[dict],
    f_note: str, v_note: str, p_note: str, o_note: str,
    tax_note: str,
    suggested_action: str,
) -> dict | None:
    claim_lines = "\n".join(
        f"  [{d['status'].upper()}] {d['claim']} (weight={d['weight']:.1f})"
        for d in t_detail[:5]
    ) or "  no claims in deteriorated state"

    prompt = f"""You are a sell/trim analyst. A deterministic scoring model evaluated {ticker}.
Write the rationale — do NOT invent or change the scores.

SELL STRENGTH: {ss:.0f}/100 → suggested action: {suggested_action}
  T (thesis, 40%):      {T}/100
{claim_lines}
  F (fundamentals, 20%): {F}/100 — {f_note}
  V (valuation, 15%):    {V}/100 — {v_note}
  P (concentration, 15%): {P}/100 — {p_note}
  O (opportunity, 10%):  {O}/100 — {o_note}

TAX NOTE (separate — never changes the action): {tax_note}

Rules:
- action must be HOLD, REVIEW, TRIM, or EXIT (not NO_ACTION)
- primary_rationale from: THESIS_BREAK, FUNDAMENTAL_DETERIORATION, VALUATION, \
PORTFOLIO_CONCENTRATION, CAPITAL_REALLOCATION, RISK_CHANGE, TAX_STRATEGY
- what_would_cause_exit: name a specific observable metric + threshold
- Do not recommend selling purely for tax efficiency

Return ONLY this JSON (no markdown):
{{
  "action": "{suggested_action}",
  "primary_rationale": "PORTFOLIO_CONCENTRATION",
  "summary": "<one-sentence plain-English summary>",
  "why_now": "<what changed or what threshold was crossed>",
  "what_would_cause_exit": "<specific observable condition>",
  "counter_case": "<strongest argument against selling>",
  "tax_note": "<copy the tax note provided above>",
  "confidence": 70
}}"""

    # Keys must match the JSON keys the LLM returns — values are ignored by _validate_schema.
    schema = {
        "action": "",
        "primary_rationale": "",
        "summary": "",
        "why_now": "",
        "what_would_cause_exit": "",
        "counter_case": "",
        "tax_note": "",
        "confidence": 0,
    }

    return ollama_client.generate_structured(
        prompt, schema,
        temperature=0.2, num_predict=600,
        _caller="sell_trim",
    )


# ── Main handler ──────────────────────────────────────────────────────────────

def _run(ctx: AgentContext) -> list[Recommendation]:
    recs: list[Recommendation] = []

    for holding in ctx.snapshot.holdings:
        ticker        = holding.ticker
        weight_pct    = holding.weight_pct
        current_price = holding.current_price

        # ── Deterministic scoring (logged before any LLM call) ───────────────
        T, t_detail = _score_T(ticker)
        F, f_note   = _score_F(ticker, current_price)
        V, v_note   = _score_V(ticker, current_price)
        P, p_note   = _score_P(ticker, weight_pct)
        O, o_note   = _score_O(ticker)

        ss = round(0.40 * T + 0.20 * F + 0.15 * V + 0.15 * P + 0.10 * O, 1)

        print(
            f"[SellTrim] {ticker}: ss={ss:.0f}  "
            f"T={T} F={F} V={V} P={P} O={O}  "
            f"weight={weight_pct:.1f}%"
        )

        # ── Gate: below threshold → NO_ACTION without LLM ───────────────────
        if ss < _NO_ACTION_THRESHOLD:
            thesis_ver = agent_db._get_thesis_version_for_hash(ticker)
            latest_q   = agent_db._get_latest_quarter_for_hash(ticker)
            h = agent_db.compute_input_hash(
                ticker, "sell_trim", current_price or 0, thesis_ver, latest_q
            )
            agent_db.upsert_no_action(
                ticker=ticker, agent_type="sell_trim",
                run_id=ctx.run_id, input_hash=h,
            )
            continue

        suggested = _action_from_strength(ss)

        # ── Tax calculation (separate; does not affect ss) ───────────────────
        tax = _tax_note(ticker, current_price)

        # ── LLM rationale ────────────────────────────────────────────────────
        try:
            result = _call_llm(
                ticker, ss, T, F, V, P, O,
                t_detail, f_note, v_note, p_note, o_note,
                tax, suggested,
            )
        except Exception as _llm_err:
            print(f"[SellTrim] LLM failed for {ticker}: {_llm_err}")
            result = None

        if result is None:
            result = {
                "action": suggested,
                "primary_rationale": _dominant_rationale(T, F, V, P, O),
                "summary": f"SellStrength {ss:.0f}: {_dominant_rationale(T, F, V, P, O).lower().replace('_', ' ')}",
                "why_now": "deterministic scoring triggered review threshold",
                "what_would_cause_exit": "see component details in action_payload",
                "counter_case": "LLM analysis unavailable",
                "tax_note": tax,
                "confidence": 45,
            }

        action = result.get("action", suggested)
        if action not in {"HOLD", "REVIEW", "TRIM", "EXIT"}:
            action = suggested

        primary_rationale = result.get("primary_rationale", "RISK_CHANGE")
        if primary_rationale not in _RATIONALE_CLASSES:
            primary_rationale = _dominant_rationale(T, F, V, P, O)

        # rec_score: centre on ss but map loosely to action severity
        action_score = {"HOLD": 25, "REVIEW": 42, "TRIM": 63, "EXIT": 80}
        rec_score = action_score.get(action, int(ss))

        # Input hash for HOLD dedup
        thesis_ver = agent_db._get_thesis_version_for_hash(ticker)
        latest_q   = agent_db._get_latest_quarter_for_hash(ticker)
        input_hash = agent_db.compute_input_hash(
            ticker, "sell_trim", current_price or 0, thesis_ver, latest_q
        ) if action == "HOLD" else None

        ev = EvidenceBundle(
            has_price=current_price > 0,
            financial_quarters=2,
            has_strategy_metadata=True,
            has_recent_fundamentals=F > 0,
            source_quality="primary_data",
            signal_directions=["sell"] if action in ("TRIM", "EXIT") else ["hold"],
            recommendation_direction="sell" if action in ("TRIM", "EXIT") else "hold",
            rule_support=0.7,
        )
        confidence = min(90, max(30, score_evidence(ev)))

        priority = "urgent" if action == "EXIT" else "high" if action == "TRIM" else "normal"

        rec = Recommendation(
            ticker=ticker,
            action=action,
            recommendation_score=rec_score,
            confidence=confidence,
            priority=priority,
            why_now=result.get("why_now"),
            rationale=result.get("summary"),
            counter_case=result.get("counter_case"),
            no_action_case=result.get("what_would_cause_exit"),
            rationale_class=primary_rationale,
            action_payload={
                "sell_strength": ss,
                "components": {"T": T, "F": F, "V": V, "P": P, "O": O},
                "component_notes": {
                    "T": [d["claim"] for d in t_detail[:3]],
                    "F": f_note, "V": v_note, "P": p_note, "O": o_note,
                },
                "tax_note": tax,
                "what_would_cause_exit": result.get("what_would_cause_exit"),
            },
            input_hash=input_hash,
            dependencies=[{
                "dependency_type": "POSITION_WEIGHT",
                "dependency_key": ticker,
                "original_value": str(weight_pct),
                "tolerance": 2.0,
                "invalidating_event": "WEIGHT_SHIFT",
            }],
        )
        recs.append(rec)

    return recs


register_agent("sell_trim", _run)
