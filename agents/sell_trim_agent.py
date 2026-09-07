from __future__ import annotations
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

_PROMPT_VERSION = "sell_trim_v2"

_RATIONALE_CLASSES = frozenset({
    "THESIS_BREAK", "FUNDAMENTAL_DETERIORATION", "VALUATION",
    "PORTFOLIO_CONCENTRATION", "CAPITAL_REALLOCATION", "RISK_CHANGE", "TAX_STRATEGY",
})

_NO_ACTION_THRESHOLD = 10   # ss below this → upsert_no_action, skip LLM

_DEFAULT_MAX_WEIGHT_PCT = 10.0   # used when thesis has no max_weight_pct set

# 0083: Map thesis valuation_framework.primary_metric → company_financials column.
# When a thesis specifies a primary_metric that matches a key here, _score_V()
# fetches historical values from that column and uses it for the percentile
# ranking instead of the default P/E (price_to_earnings) fallback.
# Metrics not in this map fall back to the existing P/E-based scoring path.
METRIC_COLUMN_MAP: dict[str, str] = {
    "pe":            "price_to_earnings",
    "forward_pe":    "price_to_earnings",   # best proxy available in stored data
    "trailing_pe":   "price_to_earnings",
    "ev_fcf":        "free_cash_flow",      # EV/FCF — use FCF for ranking
    "p_fcf":         "free_cash_flow",
    "ps":            "revenue",             # P/S — revenue as proxy
    "price_to_sales":"revenue",
    "ev_ebitda":     "operating_income",    # EBITDA proxy: operating_income
    "ev_revenue":    "revenue",
    "gross_margin":  "gross_profit",        # gross margin quality
}


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


def _ttm(values: list) -> float | None:
    """Sum of last 4 non-None values (trailing twelve months)."""
    vals = [float(v) for v in values if v is not None]
    if len(vals) >= 4:
        return sum(vals[:4])
    return None


def _yoy_growth(values: list) -> float | None:
    """YoY growth: (Q[-1] - Q[-5]) / |Q[-5]|. Requires at least 5 periods."""
    vals = [v for v in values if v is not None]
    if len(vals) < 5:
        return None
    newest, year_ago = vals[0], vals[4]
    if abs(year_ago) < 1e-6:
        return None
    return (newest - year_ago) / abs(year_ago)


def _score_F(ticker: str, current_price: float) -> tuple[int, str]:
    """F = fundamental deterioration (0–100). 20% weight.

    Uses YoY comparisons (same quarter prior year) when ≥5 periods available.
    Falls back to QoQ when < 5 periods. TTM revenue vs prior TTM is always computed
    when ≥8 periods available.
    """
    conn = _connect()
    if not conn:
        return 0, "no data"
    quarters = conn.execute(
        """SELECT revenue, gross_profit, operating_income, free_cash_flow,
                  eps_diluted, period_end
           FROM company_financials
           WHERE ticker = ? AND period_type = 'Q'
           ORDER BY period_end DESC LIMIT 9""",
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

    n = len(quarters)
    comparison_type = "YoY" if n >= 5 else "QoQ_fallback"
    score = 0
    notes: list[str] = []

    revenues   = [q["revenue"]       for q in quarters]
    gp_vals    = [q["gross_profit"]  for q in quarters]
    fcf_vals   = [q["free_cash_flow"] for q in quarters]

    if comparison_type == "YoY":
        rev_chg = _yoy_growth(revenues)
    else:
        rev_chg = ((revenues[0] - revenues[-1]) / abs(revenues[-1])
                   if revenues[-1] and abs(revenues[-1]) > 0 else None)

    if rev_chg is not None:
        if rev_chg < -0.05:
            score += 35
            notes.append(f"revenue {rev_chg*100:.0f}% {comparison_type}")
        elif rev_chg < 0:
            score += 15
            notes.append(f"revenue flat/declining ({comparison_type})")

    # TTM revenue vs prior TTM (when ≥8 quarters)
    if n >= 8:
        ttm_now  = _ttm(revenues[:4])
        ttm_prev = _ttm(revenues[4:8])
        if ttm_now is not None and ttm_prev is not None and abs(ttm_prev) > 0:
            ttm_chg = (ttm_now - ttm_prev) / abs(ttm_prev)
            if ttm_chg < -0.05 and "revenue" not in " ".join(notes):
                score += 20
                notes.append(f"TTM revenue {ttm_chg*100:.0f}% YoY")

    # Gross margin trend (YoY when available)
    if n >= 5:
        # Compare newest quarter margin vs same quarter prior year
        rev0, gp0 = revenues[0], gp_vals[0]
        rev4, gp4 = revenues[4], gp_vals[4]
        if rev0 and gp0 is not None and rev4 and gp4 is not None:
            gm_new = gp0 / rev0
            gm_old = gp4 / rev4
            diff   = gm_new - gm_old
            if diff < -0.03:
                score += 30
                notes.append(f"margin {diff*100:.1f}pp YoY")
            elif diff < 0:
                score += 10
                notes.append("slight margin erosion (YoY)")
    elif len(quarters) >= 2:
        newest, oldest = quarters[0], quarters[-1]
        if (oldest["gross_profit"] and oldest["revenue"]
                and newest["gross_profit"] and newest["revenue"]):
            gm_old = oldest["gross_profit"] / oldest["revenue"]
            gm_new = newest["gross_profit"] / newest["revenue"]
            diff   = gm_new - gm_old
            if diff < -0.03:
                score += 30
                notes.append(f"margin {diff*100:.1f}pp (QoQ)")
            elif diff < 0:
                score += 10
                notes.append("slight margin erosion (QoQ)")

    # Free cash flow — most recent quarter
    newest_fcf = fcf_vals[0] if fcf_vals else None
    if newest_fcf is not None and newest_fcf < 0:
        score += 15
        notes.append("negative FCF")

    # Analyst price target vs current price
    if est and est["price_target"] and current_price > 0:
        upside = (est["price_target"] - current_price) / current_price
        if upside < -0.15:
            score += 15
            notes.append(f"PT {upside*100:.0f}% below price")

    note_str = "; ".join(notes) or f"no material deterioration ({comparison_type})"
    return min(100, score), note_str


def _valuation_percentile(current_pe: float, historical: list[float]) -> float | None:
    """Rank current_pe within the ticker's own historical P/E distribution (0–100 percentile).

    Requires at least 4 historical values. Returns None when insufficient history.
    """
    if len(historical) < 4:
        return None
    below = sum(1 for h in historical if h < current_pe)
    return (below / len(historical)) * 100.0


def _v_score_from_percentile(pct: float) -> float:
    """Map historical percentile to a V component score (0–100)."""
    if pct > 90:
        return 90.0
    if pct > 75:
        return 70.0
    if pct > 50:
        return 45.0
    if pct > 25:
        return 20.0
    return 5.0


def _score_V(ticker: str, current_price: float) -> tuple[int, str]:
    """V = valuation risk composite (0–100). 15% weight.

    Primary: historical P/E percentile (company vs own 5-year history) when ≥4 periods.
    Secondary weighted composite: 0.30*H + 0.25*G + 0.20*FCF + 0.15*E + 0.10*C
      H   — trailing P/E (historical percentile if available, else absolute)
      G   — PEG / growth-adjusted valuation (0–100)
      FCF — FCF quality trend (0–100)
      E   — analyst recommendation sentiment (0–100)
      C   — analyst price target vs current price (0–100, capped contribution)

    Falls back gracefully: if a factor has no data, exclude it and re-normalize.
    """
    if current_price <= 0:
        return 25, "no price"

    conn = _connect()
    if not conn:
        return 25, "no data"

    quarters = conn.execute(
        """SELECT eps_diluted, free_cash_flow, price_to_earnings, period_end
           FROM company_financials
           WHERE ticker = ? AND period_type = 'Q'
           ORDER BY period_end DESC LIMIT 20""",
        (ticker,),
    ).fetchall()

    # Read thesis valuation framework for extreme_threshold override
    thesis_val_framework: dict = {}
    try:
        vf_row = conn.execute(
            "SELECT valuation_framework FROM investment_theses "
            "WHERE ticker=? AND status='ACTIVE' ORDER BY version DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        if vf_row and vf_row["valuation_framework"]:
            import json as _json
            thesis_val_framework = _json.loads(vf_row["valuation_framework"]) or {}
    except Exception:
        pass
    est = conn.execute(
        "SELECT price_target, recommendation, next_yr_eps_est, curr_yr_eps_est "
        "FROM company_estimates WHERE ticker = ? ORDER BY fetched_at DESC LIMIT 1",
        (ticker,),
    ).fetchone()
    conn.close()

    factors: dict[str, float] = {}
    notes: list[str] = []
    v_method = "absolute"

    # 0083: Route valuation engine by thesis primary_metric.
    # When the thesis specifies a primary_metric that maps to a DB column,
    # use that column's historical distribution for percentile ranking instead
    # of defaulting to P/E.  attractive_threshold / fair_value_high from the
    # framework are used for an absolute check alongside the percentile path.
    _primary_metric = (thesis_val_framework.get("primary_metric") or "").lower().strip()
    _primary_col    = METRIC_COLUMN_MAP.get(_primary_metric)
    _used_primary   = False  # set True when primary_metric path fires

    if _primary_col and quarters and _primary_col != "price_to_earnings":
        # Fetch raw column values from the stored quarters
        _hist_vals = [
            float(q[_primary_col]) for q in quarters
            if q[_primary_col] is not None
        ]
        _curr_val = _hist_vals[0] if _hist_vals else None

        if _curr_val is not None and len(_hist_vals) >= 4:
            pct = _valuation_percentile(_curr_val, _hist_vals)
            if pct is not None:
                v_method = f"primary_metric_{_primary_metric}_pct{pct:.0f}"
                factors["H"] = _v_score_from_percentile(pct)
                notes.append(
                    f"{_primary_metric}={_curr_val:.1f} ({pct:.0f}th pct of history)"
                )
                _used_primary = True

        # attractive_threshold: if current value < threshold → cheap (score down)
        _attractive = thesis_val_framework.get("attractive_threshold")
        _fvh        = thesis_val_framework.get("fair_value_high")
        if _curr_val is not None:
            if _attractive and float(_attractive) > 0 and _curr_val < float(_attractive):
                # Attractive — reduce existing H score if too high
                factors["H"] = min(factors.get("H", 25.0), 15.0)
                notes.append(
                    f"{_primary_metric} below attractive threshold ({float(_attractive):.1f})"
                )
            elif _fvh and float(_fvh) > 0 and _curr_val > float(_fvh):
                # Above fair value high → expensive
                factors["H"] = max(factors.get("H", 55.0), 70.0)
                notes.append(
                    f"{_primary_metric} above fair-value-high ({float(_fvh):.1f})"
                )

    # H — trailing P/E with historical percentile when available
    # Skip when primary_metric routing already set the H factor.
    if quarters and not _used_primary:
        ttm_eps = sum(
            float(q["eps_diluted"]) for q in quarters[:4]
            if q["eps_diluted"] is not None
        )
        if ttm_eps > 0:
            pe = current_price / ttm_eps

            # Try historical percentile using stored price_to_earnings values
            hist_pe = [float(q["price_to_earnings"]) for q in quarters
                       if q["price_to_earnings"] is not None and float(q["price_to_earnings"]) > 0]
            pct = _valuation_percentile(pe, hist_pe)

            if pct is not None:
                v_method = f"percentile_{pct:.0f}th"
                factors["H"] = _v_score_from_percentile(pct)
                if pct > 90:
                    notes.append(f"P/E={pe:.0f}x ({pct:.0f}th pct of 5yr history — extreme)")
                elif pct > 75:
                    notes.append(f"P/E={pe:.0f}x ({pct:.0f}th pct — expensive)")
                elif pct > 50:
                    notes.append(f"P/E={pe:.0f}x ({pct:.0f}th pct — elevated)")
                elif pct > 25:
                    notes.append(f"P/E={pe:.0f}x ({pct:.0f}th pct — fair)")
                else:
                    notes.append(f"P/E={pe:.0f}x ({pct:.0f}th pct — cheap vs history)")
            else:
                # Absolute fallback when < 4 historical periods
                v_method = "absolute_fallback"
                if pe > 50:
                    factors["H"] = 85.0
                    notes.append(f"P/E={pe:.0f}x (very expensive, abs)")
                elif pe > 35:
                    factors["H"] = 70.0
                    notes.append(f"P/E={pe:.0f}x (expensive, abs)")
                elif pe > 25:
                    factors["H"] = 45.0
                    notes.append(f"P/E={pe:.0f}x (elevated, abs)")
                elif pe > 15:
                    factors["H"] = 20.0
                    notes.append(f"P/E={pe:.0f}x (fair, abs)")
                else:
                    factors["H"] = 5.0
                    notes.append(f"P/E={pe:.0f}x (cheap, abs)")
        elif ttm_eps < 0:
            factors["H"] = 55.0
            notes.append("negative TTM EPS")

    # Thesis valuation framework override: extreme_threshold check
    extreme = thesis_val_framework.get("extreme_threshold")
    if extreme and "H" in factors:
        try:
            extreme_f = float(extreme)
            ttm_eps_check = sum(
                float(q["eps_diluted"]) for q in quarters[:4]
                if q["eps_diluted"] is not None
            )
            if ttm_eps_check > 0:
                pe_check = current_price / ttm_eps_check
                if pe_check > extreme_f:
                    factors["H"] = max(factors.get("H", 0), 85.0)
                    notes.append(f"above thesis extreme threshold ({extreme_f}x)")
        except (TypeError, ValueError):
            pass

    # G — growth-adjusted (PEG using forward EPS growth from estimates)
    if est and est["next_yr_eps_est"] and est["curr_yr_eps_est"]:
        try:
            curr_e = float(est["curr_yr_eps_est"])
            next_e = float(est["next_yr_eps_est"])
            if curr_e > 0 and next_e > curr_e:
                growth_pct = ((next_e - curr_e) / curr_e) * 100
                if quarters and "H" in factors:
                    ttm_eps2 = sum(
                        float(q["eps_diluted"]) for q in quarters[:4]
                        if q["eps_diluted"] is not None
                    )
                    pe2 = current_price / ttm_eps2 if ttm_eps2 > 0 else None
                    if pe2 and growth_pct > 0:
                        peg = pe2 / growth_pct
                        if peg > 3:
                            factors["G"] = 80.0
                            notes.append(f"PEG={peg:.1f} (overvalued)")
                        elif peg > 2:
                            factors["G"] = 55.0
                            notes.append(f"PEG={peg:.1f} (stretched)")
                        elif peg > 1:
                            factors["G"] = 30.0
                            notes.append(f"PEG={peg:.1f} (fair)")
                        else:
                            factors["G"] = 10.0
                            notes.append(f"PEG={peg:.1f} (growth bargain)")
            elif curr_e > 0 and next_e <= curr_e:
                factors["G"] = 65.0
                notes.append("EPS expected to decline/flat YoY")
        except (TypeError, ValueError):
            pass

    # FCF — free cash flow quality (last 4 quarters)
    if quarters:
        fcf_vals = [
            float(q["free_cash_flow"]) for q in quarters[:4]
            if q["free_cash_flow"] is not None
        ]
        if fcf_vals:
            latest_fcf = fcf_vals[0]
            if latest_fcf < 0:
                factors["FCF"] = 75.0
                notes.append("negative FCF")
            elif len(fcf_vals) >= 2 and fcf_vals[0] < fcf_vals[-1] * 0.7:
                factors["FCF"] = 50.0
                notes.append("FCF declining")
            elif latest_fcf >= 0:
                factors["FCF"] = 12.0
                notes.append("FCF positive")

    # E — analyst recommendation sentiment
    if est and est["recommendation"]:
        rec_str = (est["recommendation"] or "").lower()
        if any(x in rec_str for x in ("strong sell", "strong_sell")):
            factors["E"] = 90.0
            notes.append("analyst: strong sell")
        elif "sell" in rec_str or "underperform" in rec_str or "underweight" in rec_str:
            factors["E"] = 65.0
            notes.append(f"analyst: {est['recommendation']}")
        elif "hold" in rec_str or "neutral" in rec_str or "equal" in rec_str:
            factors["E"] = 35.0
        elif "buy" in rec_str or "outperform" in rec_str or "overweight" in rec_str:
            factors["E"] = 12.0
        elif "strong buy" in rec_str:
            factors["E"] = 5.0

    # C — consensus price target (capped contribution: max raw score 85, weight only 0.10)
    if est and est["price_target"] and current_price > 0:
        pt = float(est["price_target"])
        upside = (pt - current_price) / current_price
        if upside < -0.20:
            factors["C"] = 85.0
            notes.append(f"PT ${pt:.0f} ({upside*100:.0f}%)")
        elif upside < -0.10:
            factors["C"] = 60.0
        elif upside < -0.03:
            factors["C"] = 35.0
        elif upside < 0.05:
            factors["C"] = 20.0
        else:
            factors["C"] = 8.0

    if not factors:
        return 25, "insufficient data"

    # Weighted composite with re-normalization for missing factors
    weights = {"H": 0.30, "G": 0.25, "FCF": 0.20, "E": 0.15, "C": 0.10}
    total_w = sum(weights[k] for k in factors)
    composite = sum(factors[k] * weights[k] for k in factors) / total_w

    note_str = "; ".join(notes) if notes else f"multi-factor V ({v_method})"
    return min(100, max(0, round(composite))), note_str


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
    decision_quality_note: str = "",
) -> dict | None:
    claim_lines = "\n".join(
        f"  [{d['status'].upper()}] {d['claim']} (weight={d['weight']:.1f})"
        for d in t_detail[:5]
    ) or "  no claims in deteriorated state"

    dq_section = f"\nHISTORICAL DECISION QUALITY NOTE: {decision_quality_note}" if decision_quality_note else ""

    prompt = f"""You are a sell/trim analyst. A deterministic scoring model evaluated {ticker}.
Write the rationale — do NOT invent or change the scores.

SELL STRENGTH: {ss:.0f}/100 → suggested action: {suggested_action}
  T (thesis, 40%):      {T}/100
{claim_lines}
  F (fundamentals, 20%): {F}/100 — {f_note}
  V (valuation, 15%):    {V}/100 — {v_note}
  P (concentration, 15%): {P}/100 — {p_note}
  O (opportunity, 10%):  {O}/100 — {o_note}{dq_section}

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
        # Include decision quality note if significant historical pattern exists
        dq_note = ""
        try:
            from agents.decision_quality import get_decision_quality_note
            dq_note = get_decision_quality_note("sell_trim", suggested)
        except Exception:
            pass

        try:
            result = _call_llm(
                ticker, ss, T, F, V, P, O,
                t_detail, f_note, v_note, p_note, o_note,
                tax, suggested,
                decision_quality_note=dq_note,
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
                "trim_fraction": 0.5 if action == "TRIM" else None,
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
