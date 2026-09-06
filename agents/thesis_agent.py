"""Thesis Monitor Agent — evaluates investment thesis pillars deterministically,
then uses LLM for qualitative signals and human-readable reasons.

Evaluation flow per active thesis:
  1. Load pillars + metrics + rules from DB
  2. Force-refresh financials on earnings trigger
  3. Deterministic metric pass: apply healthy/warning/violation rules against
     company_financials; enforce persistence requirement
  4. LLM pass: generate per-pillar reasons + evaluate QUALITATIVE_SIGNAL rules
  5. Write pillar statuses to thesis_pillars (status, score, confidence, reason)
  6. Critical pillar check → THESIS_CRITICAL_VIOLATION finding + EXIT_REVIEW rec
  7. Composite score + rule evaluation → EXIT / TRIM / BUY recommendations

Write boundary: only writes to thesis_pillars and agent_findings/recommendations.
Never writes to thesis_metrics, thesis_rules, or structural pillar fields.
"""
import json
import sqlite3
from pathlib import Path

import agent_db
import financials_fetcher
import ollama_client
from .confidence import calculate_confidence
from .contracts import AgentContext, EvidenceBundle, Recommendation
from .orchestrator import register_agent

_DB = Path(__file__).resolve().parent.parent / "out" / "investment.db"

# ── Status vocabulary ──────────────────────────────────────────────────────────

_STATUS_SCORE: dict[str, float] = {
    "STRONG":   95.0,
    "HEALTHY":  80.0,
    "WATCH":    65.0,
    "WARNING":  40.0,
    "VIOLATED": 10.0,
    "UNKNOWN":  50.0,
}

# Composite thresholds for EXIT / TRIM / ADD rule evaluation
_EXIT_THRESHOLD = 50.0
_TRIM_THRESHOLD = 65.0
_ADD_THRESHOLD  = 80.0


# ── Financial data helpers ─────────────────────────────────────────────────────

def _load_financial_rows(ticker: str, period_type: str = "Q", limit: int = 10) -> list[dict]:
    """Return last `limit` company_financials rows, oldest→newest.

    Tries the canonical ticker first, then the alternate dot/hyphen form so that
    BRK-B (thesis/holding format) matches BRK.B (yfinance storage format).
    """
    if not _DB.exists():
        return []

    def _fetch(t: str) -> list[dict]:
        try:
            conn = sqlite3.connect(str(_DB), timeout=5)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM company_financials "
                "WHERE ticker=? AND period_type=? ORDER BY period_end DESC LIMIT ?",
                (t, period_type, limit),
            ).fetchall()
            conn.close()
            return [dict(r) for r in reversed(rows)]
        except Exception:
            return []

    rows = _fetch(ticker)
    if not rows:
        # Try alternate format: BRK-B ↔ BRK.B
        alt = ticker.replace("-", ".") if "-" in ticker else ticker.replace(".", "-")
        if alt != ticker:
            rows = _fetch(alt)
    return rows


def _pct(v: float | None) -> float | None:
    return v * 100 if v is not None else None


def _safe_div(a, b) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _compute_metric_value(metric_key: str, rows: list[dict], idx: int) -> float | None:
    """Compute a derived or direct metric for rows[idx], using prior rows for YoY."""
    if not rows or not (0 <= idx < len(rows)):
        return None
    r = rows[idx]

    # Aliases — normalise variant keys to canonical form
    _ALIASES = {
        "cash_and_equivalents":  "cash",
        "revenue_yoy":           "revenue_growth_yoy",
        "revenue_growth":        "revenue_growth_yoy",
        "fcf":                   "free_cash_flow",
        "free_cash_flow_annual": "free_cash_flow",
        "operating_margin_pct":  "operating_margin",
        "annual_fcf":            "free_cash_flow",
    }
    key = _ALIASES.get(metric_key, metric_key)

    # Billion-scaled FCF: "annual_fcf_usd_b" → free_cash_flow / 1e9
    if metric_key == "annual_fcf_usd_b":
        raw = r.get("free_cash_flow")
        return raw / 1e9 if raw is not None else None

    if key == "gross_margin":
        return _pct(_safe_div(r.get("gross_profit"), r.get("revenue")))
    if key == "operating_margin":
        return _pct(_safe_div(r.get("operating_income"), r.get("revenue")))
    if key == "net_margin":
        return _pct(_safe_div(r.get("net_income"), r.get("revenue")))
    if key == "fcf_margin":
        return _pct(_safe_div(r.get("free_cash_flow"), r.get("revenue")))
    if key == "net_debt":
        td   = r.get("total_debt")
        cash = r.get("cash")
        return (td - cash) if td is not None and cash is not None else None
    if key == "debt_to_equity":
        return _safe_div(r.get("total_debt"), r.get("total_equity"))
    if key == "fcf_to_net_income_ratio":
        return _safe_div(r.get("free_cash_flow"), r.get("net_income"))
    if key == "revenue_growth_yoy":
        if idx >= 4:
            prev = rows[idx - 4].get("revenue")
            curr = r.get("revenue")
            return _pct(_safe_div((curr - prev) if curr is not None and prev is not None else None, prev))
        return None
    if key == "net_income_yoy":
        if idx >= 4:
            prev = rows[idx - 4].get("net_income")
            curr = r.get("net_income")
            return _pct(_safe_div((curr - prev) if curr is not None and prev is not None else None, prev))
        return None
    # Direct columns
    direct = ("revenue", "gross_profit", "operating_income", "net_income",
               "free_cash_flow", "total_debt", "cash", "total_equity", "eps_diluted")
    if key in direct:
        return r.get(key)
    return None


# ── Rule evaluation ────────────────────────────────────────────────────────────

def _eval_rule(rule_json_str: str | None, value: float | None) -> bool | None:
    """Evaluate a stored rule against a value.

    Accepts two formats:
      - JSON object: {"operator": ">=", "value": 5.0} or {"operator": "BETWEEN", "min": 60, "max": 70}
      - Plain text (legacy claims format): "> 5.0%", ">= 4.2", "60% - 70%", "< 2.0%"

    Returns True (condition met), False (not met), None (can't evaluate).
    """
    import re as _re
    if not rule_json_str or value is None:
        return None
    # Try JSON format first
    try:
        rule = json.loads(rule_json_str)
        op = rule.get("operator", "")
        if op == ">=":    return value >= rule["value"]
        if op == ">":     return value > rule["value"]
        if op == "<=":    return value <= rule["value"]
        if op == "<":     return value < rule["value"]
        if op in ("==", "="): return value == rule["value"]
        if op == "BETWEEN": return rule["min"] <= value <= rule["max"]
        return None
    except (json.JSONDecodeError, TypeError, KeyError):
        pass
    # Fallback: parse plain-text rules like "> 5.0%", "60% - 70%", ">= 4.2"
    s = rule_json_str.strip()
    # BETWEEN: "60-70%" or "60% - 70%" or "60 - 70"
    between = _re.match(r'^([\d.]+)\s*%?\s*[-–]\s*([\d.]+)', s)
    if between:
        lo, hi = float(between.group(1)), float(between.group(2))
        return lo <= value <= hi
    # Operator + number (optional % sign and trailing text)
    m = _re.match(r'^([><=!]{1,2})\s*([\d.]+)', s)
    if m:
        op, num = m.group(1), float(m.group(2))
        if op == ">":     return value > num
        if op == ">=":    return value >= num
        if op == "<":     return value < num
        if op == "<=":    return value <= num
        if op in ("==", "="): return value == num
    return None


def _metric_level_status(metric: dict, fin_rows: list[dict]) -> tuple[str, float | None]:
    """Evaluate one thesis_metric against financial rows with persistence check.

    Returns (status, current_value) where status ∈ {HEALTHY, WARNING, VIOLATED, WATCH, UNKNOWN}.

    Persistence rule:
      - If current period is in violation zone AND persistence_periods > 1:
        - VIOLATED only if ALL of the last N periods are violated
        - Otherwise WARNING (elevated — in violation zone but not confirmed)
      - Healthy is checked before warning to avoid boundary issues.
    """
    persistence = int(metric.get("persistence_periods") or 1)
    n = len(fin_rows)
    if n == 0:
        return "UNKNOWN", None

    values = [_compute_metric_value(metric["metric_key"], fin_rows, i) for i in range(n)]
    current_value = values[-1] if values else None

    if current_value is None:
        return "UNKNOWN", None

    violation_rule = metric.get("violation_rule_json")
    warning_rule   = metric.get("warning_rule_json")
    healthy_rule   = metric.get("healthy_rule_json")

    current_violates = (_eval_rule(violation_rule, current_value) is True)

    if current_violates:
        if persistence > 1:
            recent = values[-persistence:]
            known  = [v for v in recent if v is not None]
            if len(known) >= persistence and all(_eval_rule(violation_rule, v) for v in known):
                return "VIOLATED", current_value
            # In violation zone but persistence not confirmed — elevated warning
            return "WARNING", current_value
        return "VIOLATED", current_value

    # Check healthy before warning to handle threshold boundaries correctly
    if _eval_rule(healthy_rule, current_value) is True:
        return "HEALTHY", current_value

    if _eval_rule(warning_rule, current_value) is True:
        return "WARNING", current_value

    return "WATCH", current_value


def _resolve_pillar_status(metric_statuses: list[str]) -> tuple[str, float]:
    """Combine per-metric statuses into a pillar status + score.

    Worst metric wins: VIOLATED > WARNING > WATCH > HEALTHY > STRONG.
    STRONG requires ≥2 all-HEALTHY metrics.
    """
    if not metric_statuses or all(s == "UNKNOWN" for s in metric_statuses):
        return "UNKNOWN", _STATUS_SCORE["UNKNOWN"]
    known = [s for s in metric_statuses if s != "UNKNOWN"]
    if not known:
        return "UNKNOWN", _STATUS_SCORE["UNKNOWN"]
    if "VIOLATED" in known:
        return "VIOLATED", _STATUS_SCORE["VIOLATED"]
    if "WARNING" in known:
        return "WARNING", _STATUS_SCORE["WARNING"]
    if "WATCH" in known:
        return "WATCH", _STATUS_SCORE["WATCH"]
    # All HEALTHY or better
    if len(known) >= 2:
        return "STRONG", _STATUS_SCORE["STRONG"]
    return "HEALTHY", _STATUS_SCORE["HEALTHY"]


# ── LLM refinement ─────────────────────────────────────────────────────────────

_LLM_SYSTEM = (
    "You are an investment analyst writing concise pillar evaluation summaries. "
    "You receive deterministic metric evaluation results and must write a clear "
    "1-2 sentence reason for each pillar's status, referencing actual numbers. "
    "If QUALITATIVE_SIGNAL rules are listed, evaluate whether each signal is "
    "present or absent. Do NOT change statuses — only write reasons and evaluate signals."
)

_LLM_SCHEMA = {
    "pillar_reasons": [
        {"pillar_name": "", "reason": ""}
    ],
    "qualitative_signals": [
        {"signal_name": "", "present": False, "confidence": 60, "note": ""}
    ],
    "overall_summary": "",
}


def _llm_refine(
    ticker: str,
    thesis: dict,
    pillar_eval_data: list[dict],
    fin_summary: str,
    qualitative_rules: list[dict],
) -> dict:
    """One LLM call per thesis: generates per-pillar reasons + qualitative signal eval."""
    pillar_blocks = "\n".join(
        f"  {pd['name']} → {pd['det_status']} | {pd['metrics_detail']}"
        for pd in pillar_eval_data
    )
    qual_block = ""
    if qualitative_rules:
        qual_block = "\n\nQUALITATIVE SIGNALS to evaluate:\n" + "\n".join(
            f"  - {r.get('signal_name', 'signal')}: {r.get('description', r.get('condition', ''))}"
            for r in qualitative_rules
        )

    prompt = (
        f"{_LLM_SYSTEM}\n\n"
        f"Ticker: {ticker}\n"
        f"Thesis: {thesis.get('thesis_summary') or thesis.get('summary', '(no summary)')}\n\n"
        f"DETERMINISTIC PILLAR RESULTS:\n{pillar_blocks}\n\n"
        f"FINANCIAL CONTEXT:\n{fin_summary or '(no financial data available)'}"
        f"{qual_block}\n\n"
        "Return JSON with pillar_reasons (one entry per pillar, exact pillar_name), "
        "qualitative_signals (empty list if none given), and overall_summary."
    )
    return ollama_client.generate_structured(
        prompt=prompt,
        schema=_LLM_SCHEMA,
        model="mlx-community/Qwen3.6-35B-A3B-4bit",
        temperature=0.2,
        num_predict=1500,
        thinking=False,
        retries=2,
    )


# ── Evidence builder ───────────────────────────────────────────────────────────

def _evidence(fin_rows: list[dict]) -> EvidenceBundle:
    quarters = len(fin_rows)
    return EvidenceBundle(
        has_price=True,
        financial_quarters=quarters,
        has_strategy_metadata=True,
        has_recent_fundamentals=(quarters >= 2),
        source_quality="official_filing" if quarters >= 2 else "secondary_commentary",
    )


# ── Main agent entry point ─────────────────────────────────────────────────────

def run_thesis_monitor(ctx: AgentContext) -> list[Recommendation]:
    recommendations: list[Recommendation] = []
    snapshot = ctx.snapshot

    # Earnings trigger: bypass financials cache
    if ctx.trigger_type == "earnings" and ctx.ticker:
        print(f"[thesis_monitor] Earnings trigger for {ctx.ticker} — bypassing cache")
        financials_fetcher.fetch_all([ctx.ticker], force=True)

    tickers = (
        [ctx.ticker] if ctx.ticker
        else [h.ticker for h in snapshot.holdings]
    )

    for ticker in tickers:
        thesis = agent_db.get_active_thesis(ticker)
        if not thesis:
            continue

        pillars = thesis.get("pillars", [])
        if not pillars:
            continue

        thesis_id = thesis["id"]
        metrics_by_pillar = {p["id"]: agent_db.get_thesis_metrics(p["id"]) for p in pillars}
        rules = agent_db.get_thesis_rules(thesis_id)

        # Load quarterly rows (8 = 2 years, enough for YoY with persistence up to 4)
        fin_rows = _load_financial_rows(ticker, period_type="Q", limit=8)

        # ── Deterministic metric evaluation ───────────────────────────────
        pillar_eval_data: list[dict] = []

        for pillar in pillars:
            metrics = metrics_by_pillar.get(pillar["id"], [])
            metric_statuses: list[str] = []
            metrics_detail_parts: list[str] = []

            for m in metrics:
                status, value = _metric_level_status(m, fin_rows)
                metric_statuses.append(status)
                val_str = f"{value:.2f}" if value is not None else "N/A"
                metrics_detail_parts.append(f"{m['metric_key']}={val_str}[{status}]")

            det_status, det_score = _resolve_pillar_status(metric_statuses)
            pillar_eval_data.append({
                "id":            pillar["id"],
                "name":          pillar["name"],
                "critical":      bool(pillar.get("critical")),
                "importance":    float(pillar.get("importance") or 0),
                "det_status":    det_status,
                "det_score":     det_score,
                "metrics_detail": "; ".join(metrics_detail_parts) or "(no quantitative metrics)",
            })

        # ── LLM refinement: reasons + qualitative signals ─────────────────
        fin_summary = financials_fetcher.get_financial_summary(ticker)
        qualitative_rules = []
        for r in rules:
            if r["rule_type"] == "QUALITATIVE_SIGNAL":
                try:
                    qualitative_rules.append(json.loads(r["rule_json"]))
                except (json.JSONDecodeError, TypeError):
                    pass

        try:
            llm_out = _llm_refine(ticker, thesis, pillar_eval_data, fin_summary, qualitative_rules)
        except Exception as e:
            print(f"[thesis_monitor] LLM refinement failed for {ticker}: {e}")
            llm_out = {}

        reason_by_name = {}
        for item in llm_out.get("pillar_reasons", []):
            if isinstance(item, dict) and item.get("pillar_name"):
                reason_by_name[item["pillar_name"]] = item.get("reason", "")
        overall_summary = llm_out.get("overall_summary", "")

        # ── Write pillar statuses to DB ───────────────────────────────────
        updated_pillars: list[dict] = []
        for pd in pillar_eval_data:
            reason = reason_by_name.get(pd["name"]) or pd["metrics_detail"]
            confidence = 80.0 if fin_rows else 35.0
            agent_db.update_pillar_status(
                pd["id"],
                pd["det_status"],
                pd["det_score"],
                confidence,
                reason,
            )
            updated_pillars.append({**pd, "confidence": confidence})
            print(
                f"[thesis_monitor] {ticker}/{pd['name']}: "
                f"{pd['det_status']} score={pd['det_score']:.0f}"
            )

        # ── Composite health score ────────────────────────────────────────
        total_weight = sum(p["importance"] for p in updated_pillars)
        composite = (
            sum(p["importance"] * p["det_score"] for p in updated_pillars) / total_weight
            if total_weight > 0 else 50.0
        )

        any_violated = any(p["det_status"] == "VIOLATED" for p in updated_pillars)
        any_warning  = any(p["det_status"] in ("WARNING", "WATCH") for p in updated_pillars)

        # ── Critical pillar check → EXIT_REVIEW immediately ───────────────
        critical_violated = [
            p for p in updated_pillars if p["critical"] and p["det_status"] == "VIOLATED"
        ]
        if critical_violated:
            names = ", ".join(p["name"] for p in critical_violated)
            print(f"[thesis_monitor] {ticker}: CRITICAL VIOLATION — {names}")
            agent_db.insert_finding(
                run_id=ctx.run_id,
                finding_type="THESIS_CRITICAL_VIOLATION",
                ticker=ticker,
                summary=(
                    f"{ticker}: critical pillar(s) VIOLATED — {names}. "
                    f"Composite: {composite:.0f}. {overall_summary}"
                ),
                severity=90,
                confidence=85,
            )
            recommendations.append(Recommendation(
                ticker=ticker,
                action="EXIT_REVIEW",
                recommendation_score=90,
                confidence=calculate_confidence(_evidence(fin_rows)),
                priority="urgent",
                why_now=f"Critical thesis pillar VIOLATED: {names}",
                rationale=f"Composite health score {composite:.0f}/100. {overall_summary}",
                counter_case="Verify metric data quality — may reflect a one-time item.",
                action_payload={
                    "thesis_id":        thesis_id,
                    "critical_violated": [p["name"] for p in critical_violated],
                    "composite_score":  round(composite, 1),
                    "trigger":          "critical_pillar_violation",
                },
                dependencies=[{
                    "dependency_type": "THESIS_VERSION",
                    "dependency_key": ticker,
                    "original_value": thesis.get("version", 1),
                    "tolerance": 0,
                    "invalidating_event": "THESIS_CHANGED",
                }],
            ))

        # ── Overall thesis finding (always emitted) ───────────────────────
        severity = 80 if any_violated else (50 if any_warning else 20)
        agent_db.insert_finding(
            run_id=ctx.run_id,
            finding_type="thesis_evaluation",
            ticker=ticker,
            summary=f"{ticker} thesis composite health: {composite:.0f}/100. {overall_summary}",
            severity=severity,
            confidence=80 if fin_rows else 40,
        )
        print(f"[thesis_monitor] {ticker}: composite={composite:.0f} — {overall_summary[:80]}")

        # ── EXIT rule (non-critical path, composite < threshold) ──────────
        exit_rules = [r for r in rules if r["rule_type"] == "EXIT"]
        if not critical_violated and composite < _EXIT_THRESHOLD:
            rule_cond = _rule_condition(exit_rules)
            recommendations.append(Recommendation(
                ticker=ticker,
                action="EXIT_REVIEW",
                recommendation_score=75,
                confidence=calculate_confidence(_evidence(fin_rows)),
                priority="high",
                why_now=f"Composite thesis health {composite:.0f}/100 below exit threshold ({_EXIT_THRESHOLD:.0f}).",
                rationale=rule_cond or overall_summary,
                counter_case="Confirm metrics are not distorted by one-time items before exiting.",
                action_payload={
                    "thesis_id":       thesis_id,
                    "composite_score": round(composite, 1),
                    "trigger":         "low_composite_score",
                    "violated_pillars": [p["name"] for p in updated_pillars if p["det_status"] == "VIOLATED"],
                },
                dependencies=[{
                    "dependency_type": "THESIS_VERSION",
                    "dependency_key": ticker,
                    "original_value": thesis.get("version", 1),
                    "tolerance": 0,
                    "invalidating_event": "THESIS_CHANGED",
                }],
            ))

        # ── TRIM rule (composite in distress band with violations) ─────────
        trim_rules = [r for r in rules if r["rule_type"] == "TRIM"]
        if _EXIT_THRESHOLD <= composite < _TRIM_THRESHOLD and any_violated:
            rule_cond = _rule_condition(trim_rules)
            recommendations.append(Recommendation(
                ticker=ticker,
                action="TRIM",
                recommendation_score=60,
                confidence=calculate_confidence(_evidence(fin_rows)),
                priority="normal",
                why_now=(
                    f"Composite health {composite:.0f}/100 with pillar violation(s) — "
                    "trimming may reduce risk while monitoring recovery."
                ),
                rationale=rule_cond or overall_summary,
                counter_case="Monitor for thesis recovery before trimming.",
                action_payload={
                    "thesis_id":       thesis_id,
                    "composite_score": round(composite, 1),
                    "trigger":         "trim_rule",
                },
                dependencies=[{
                    "dependency_type": "THESIS_VERSION",
                    "dependency_key": ticker,
                    "original_value": thesis.get("version", 1),
                    "tolerance": 0,
                    "invalidating_event": "THESIS_CHANGED",
                }],
            ))

        # ── ADD rule (all clear, composite strong) ────────────────────────
        add_rules = [r for r in rules if r["rule_type"] == "ADD"]
        if composite >= _ADD_THRESHOLD and not any_violated and not any_warning:
            rule_cond = _rule_condition(add_rules)
            recommendations.append(Recommendation(
                ticker=ticker,
                action="BUY",
                recommendation_score=70,
                confidence=calculate_confidence(_evidence(fin_rows)),
                priority="normal",
                why_now=(
                    f"All thesis pillars HEALTHY/STRONG (composite {composite:.0f}/100) — "
                    "ADD conditions met."
                ),
                rationale=rule_cond or overall_summary,
                counter_case="Check position sizing — may already be at target weight.",
                action_payload={
                    "thesis_id":       thesis_id,
                    "composite_score": round(composite, 1),
                    "trigger":         "add_rule",
                },
                dependencies=[{
                    "dependency_type": "THESIS_VERSION",
                    "dependency_key": ticker,
                    "original_value": thesis.get("version", 1),
                    "tolerance": 0,
                    "invalidating_event": "THESIS_CHANGED",
                }],
            ))

    return recommendations


def _rule_condition(rules: list[dict]) -> str:
    """Extract human-readable condition text from the first matching rule."""
    if not rules:
        return ""
    try:
        return json.loads(rules[0]["rule_json"]).get("condition", "")
    except (json.JSONDecodeError, TypeError, KeyError):
        return ""


register_agent("thesis_monitor", run_thesis_monitor)
