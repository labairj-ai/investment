"""Portfolio Guardian Agent (Phase 3).

Runs four deterministic checks on every holding and layer, then calls
the LLM only for positions that crossed a materiality threshold. Severity
is computed deterministically — the LLM adds prose, not numbers.

Returns [] (no trade recommendations). All output goes to agent_findings.
"""
import math
import time

import agent_db
import ollama_client
from strategy_config import (
    LAYER_TARGETS, LAYER_NAMES, LAYER_LABELS, DRIFT_THRESHOLD, HOLDING_GROSS_DOM,
)

# Reverse map: "Layer 1: L1 Structural Ballast" -> 1
_LABEL_TO_INT: dict[str, int] = {v: k for k, v in LAYER_LABELS.items()}
from .contracts import AgentContext, Recommendation
from .orchestrator import register_agent

# --- Thresholds ----------------------------------------------------------------
_IMPACT_THRESHOLD_PP = 0.35   # portfolio NAV pp: weight_pct * |change_pct| / 100
_Z_THRESHOLD         = 2.0    # standard deviations above 20-day historical vol
_HV20_MIN_DAYS       = 5      # minimum trading days needed to compute HV20

# --- LLM schema ---------------------------------------------------------------
_POSITION_SCHEMA = {
    "type": "object",
    "properties": {
        "summary":               {"type": "string"},
        "why_now":               {"type": "string"},
        "portfolio_implication": {"type": "string"},
        "no_action_case":        {"type": "string"},
        "suggested_action":      {"type": "string", "enum": ["REVIEW"]},
    },
    "required": ["summary", "why_now", "portfolio_implication",
                 "no_action_case", "suggested_action"],
}

_SYSTEM = (
    "You are a portfolio risk analyst. You receive structured data about a "
    "flagged equity position. Write concise, factual risk commentary. "
    "Do not recommend buying or selling — only flag for review. "
    "suggested_action must always be REVIEW."
)


# --- Data helpers -------------------------------------------------------------

def _latest_holding_rows() -> list[dict]:
    """Return the most recent holding_day row for every ticker."""
    conn = agent_db._connect()
    rows = conn.execute(
        """SELECT h.day, h.ticker, h.layer, h.change_pct, h.weight_pct, h.value
           FROM holding_day h
           INNER JOIN (
               SELECT ticker, MAX(day) AS max_day
               FROM holding_day
               GROUP BY ticker
           ) latest ON h.ticker = latest.ticker AND h.day = latest.max_day"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _latest_layer_rows() -> list[dict]:
    """Return the most recent layer_day row for every layer."""
    conn = agent_db._connect()
    rows = conn.execute(
        """SELECT l.day, l.layer, l.weight_pct
           FROM layer_day l
           INNER JOIN (
               SELECT layer, MAX(day) AS max_day
               FROM layer_day
               GROUP BY layer
           ) latest ON l.layer = latest.layer AND l.day = latest.max_day"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _compute_hv20(ticker: str) -> float | None:
    """Annualised HV20 from the last 20 holding_day.change_pct rows."""
    conn = agent_db._connect()
    rows = conn.execute(
        "SELECT change_pct FROM holding_day WHERE ticker=? ORDER BY day DESC LIMIT 20",
        (ticker,),
    ).fetchall()
    conn.close()
    returns = [r[0] / 100.0 for r in rows if r[0] is not None]
    if len(returns) < _HV20_MIN_DAYS:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(variance * 252)  # annualised


# --- Severity (deterministic) ------------------------------------------------

def _layer_severity(drift_pp: float) -> int:
    """Severity for layer drift: 5pp → 70, 8pp → 94, 10pp → 100."""
    return min(100, 30 + int(abs(drift_pp) * 8))


def _position_severity(triggers: dict) -> int:
    """Max deterministic severity across all triggered position checks."""
    scores: list[int] = []
    if "concentration" in triggers:
        w = triggers["concentration"]["weight_pct"]
        scores.append(min(100, 40 + int((w - HOLDING_GROSS_DOM) * 5)))
    if "impact" in triggers:
        pp = abs(triggers["impact"]["impact_pp"])
        scores.append(min(100, int(pp * 100 + 25)))
    if "z_score" in triggers:
        z = triggers["z_score"]["z"]
        scores.append(min(100, 20 + int(z * 20)))
    return max(scores) if scores else 50


# --- LLM call ----------------------------------------------------------------

def _llm_prose(ticker: str, layer: int, weight_pct: float,
               change_pct: float, triggers: dict) -> dict | None:
    trigger_lines = []
    if "concentration" in triggers:
        trigger_lines.append(
            f"  Position concentration: {weight_pct:.1f}% weight "
            f"(threshold {HOLDING_GROSS_DOM:.0f}%)"
        )
    if "impact" in triggers:
        pp = triggers["impact"]["impact_pp"]
        trigger_lines.append(
            f"  Portfolio NAV impact: {pp:+.2f}pp "
            f"({weight_pct:.1f}% weight × {change_pct:+.2f}% daily move)"
        )
    if "z_score" in triggers:
        z  = triggers["z_score"]["z"]
        hv = triggers["z_score"]["hv20_pct"]
        trigger_lines.append(
            f"  Abnormal move: Z={z:.1f} (|{change_pct:+.2f}%| vs "
            f"HV20={hv:.1f}% annualised, threshold Z≥2)"
        )

    prompt = (
        f"{_SYSTEM}\n\n"
        f"Ticker: {ticker}  Layer: {layer}  Weight: {weight_pct:.1f}%  "
        f"Daily return: {change_pct:+.2f}%\n\n"
        f"Triggered checks:\n" + "\n".join(trigger_lines) + "\n\n"
        "Return JSON matching the schema. summary: 1 sentence. "
        "why_now: why this matters today. portfolio_implication: portfolio-level "
        "consequence. no_action_case: strongest argument to wait. "
        "suggested_action must be REVIEW."
    )
    try:
        out = ollama_client.generate_structured(
            prompt=prompt,
            schema=_POSITION_SCHEMA,
            model="mlx-community/Qwen3.6-35B-A3B-4bit",
            temperature=0.2,
            num_predict=600,
            thinking=False,
            retries=2,
        )
        if isinstance(out, dict) and out.get("suggested_action") == "REVIEW":
            return out
        print(f"[guardian] {ticker}: LLM returned invalid schema — using fallback")
    except Exception as e:
        print(f"[guardian] {ticker}: LLM failed: {e}")
    return None


def _fallback_summary(ticker: str, triggers: dict) -> tuple[str, str]:
    parts = []
    if "concentration" in triggers:
        w = triggers["concentration"]["weight_pct"]
        parts.append(f"position concentration {w:.1f}%")
    if "impact" in triggers:
        pp = triggers["impact"]["impact_pp"]
        parts.append(f"NAV impact {pp:+.2f}pp")
    if "z_score" in triggers:
        z = triggers["z_score"]["z"]
        parts.append(f"Z={z:.1f}")
    summary  = f"{ticker}: flagged — " + ", ".join(parts)
    why_now  = "Deterministic materiality threshold crossed today."
    return summary, why_now


# --- Main agent entry point --------------------------------------------------

def run_portfolio_guardian(ctx: AgentContext) -> list[Recommendation]:
    print("[guardian] Starting Portfolio Guardian sweep")

    # ── 1. Layer drift ────────────────────────────────────────────────────────
    layer_rows = _latest_layer_rows()
    for row in layer_rows:
        layer_label = row["layer"]
        layer_num   = _LABEL_TO_INT.get(layer_label)
        weight_pct  = row["weight_pct"]
        target      = LAYER_TARGETS.get(layer_num) if layer_num else None
        if target is None:
            continue
        drift = weight_pct - target
        if abs(drift) < DRIFT_THRESHOLD:
            continue
        severity = _layer_severity(drift)
        layer_name = LAYER_NAMES.get(layer_num, layer_label)
        direction  = "over" if drift > 0 else "under"
        summary = (
            f"{layer_name}: {direction}weight by {abs(drift):.1f}pp "
            f"({weight_pct:.1f}% actual vs {target:.0f}% target)"
        )
        fid = agent_db.insert_finding(
            run_id=ctx.run_id,
            finding_type="layer_drift",
            ticker=None,
            severity=severity,
            confidence=90,
            summary=summary,
            why_now=f"Layer weight has drifted {abs(drift):.1f}pp from target — "
                    f"rebalancing consideration.",
            metrics={"layer": layer_num, "weight_pct": weight_pct,
                     "target_pct": target, "drift_pp": round(drift, 2)},
        )
        print(f"[guardian] Layer drift finding #{fid}: {summary} (severity={severity})")

    # ── 2. Per-position checks ────────────────────────────────────────────────
    holding_rows = _latest_holding_rows()
    if not holding_rows:
        print("[guardian] No holding_day data — skipping position checks")
        return []

    for row in holding_rows:
        ticker     = row["ticker"]
        weight_pct = row["weight_pct"] or 0.0
        change_pct = row["change_pct"]  # may be None if no price change recorded

        triggers: dict = {}

        # Check A: position concentration
        if weight_pct > HOLDING_GROSS_DOM:
            triggers["concentration"] = {"weight_pct": weight_pct}

        if change_pct is not None:
            # Check B: portfolio NAV contribution
            impact_pp = weight_pct * change_pct / 100.0
            if abs(impact_pp) > _IMPACT_THRESHOLD_PP:
                triggers["impact"] = {
                    "impact_pp": round(impact_pp, 3),
                    "weight_pct": weight_pct,
                    "change_pct": change_pct,
                }

            # Check C: volatility-normalised Z-score
            hv20 = _compute_hv20(ticker)
            if hv20 and hv20 > 0:
                daily_vol = hv20 / math.sqrt(252)
                z = abs(change_pct / 100.0) / daily_vol
                if z >= _Z_THRESHOLD:
                    triggers["z_score"] = {
                        "z": round(z, 2),
                        "hv20_pct": round(hv20 * 100, 1),
                        "change_pct": change_pct,
                    }

        if not triggers:
            continue

        # Deterministic severity
        severity = _position_severity(triggers)

        # LLM prose (only if we have change_pct — concentration-only findings use fallback)
        llm = None
        if change_pct is not None and any(k in triggers for k in ("impact", "z_score")):
            llm = _llm_prose(
                ticker=ticker,
                layer=row["layer"],
                weight_pct=weight_pct,
                change_pct=change_pct,
                triggers=triggers,
            )

        if llm:
            summary  = llm["summary"]
            why_now  = llm["why_now"]
            metrics  = {
                "portfolio_implication": llm["portfolio_implication"],
                "no_action_case":        llm["no_action_case"],
                "suggested_action":      "REVIEW",
                **{k: v for k, v in triggers.items()},
            }
        else:
            summary, why_now = _fallback_summary(ticker, triggers)
            metrics = {"suggested_action": "REVIEW", **triggers}

        fid = agent_db.insert_finding(
            run_id=ctx.run_id,
            finding_type="position_risk",
            ticker=ticker,
            severity=severity,
            confidence=80 if llm else 65,
            summary=summary,
            why_now=why_now,
            metrics=metrics,
        )
        print(f"[guardian] Position finding #{fid}: {ticker} "
              f"triggers={list(triggers)} severity={severity}")

    print("[guardian] Sweep complete")
    return []


register_agent("portfolio_guardian", run_portfolio_guardian)
