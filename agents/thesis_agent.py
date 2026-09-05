"""Thesis Monitor Agent — evaluates investment thesis pillars against current data.

Runs for every holding that has an ACTIVE thesis. For each thesis:
- Fetches current financial data (force-refreshes when triggered by earnings)
- Calls LLM to evaluate each pillar against current conditions and thresholds
- Updates thesis_pillars.status, score, confidence, last_evaluated_at
- Creates a REVIEW_THESIS recommendation when overall status is REVIEW or worse
"""
import json

import financials_fetcher
import agent_db
import ollama_client
from .contracts import AgentContext, EvidenceBundle, Recommendation
from .confidence import calculate_confidence
from .orchestrator import register_agent


_VALID_PILLAR_STATUSES = {"INTACT", "WEAKENED", "VIOLATED"}

# Maps overall thesis status to recommendation priority
_PRIORITY = {"REVIEW": "normal", "DETERIORATING": "high", "VIOLATED": "urgent"}

# Numeric rank for computing recommendation_score
_STATUS_RANK = {"INTACT": 0, "MONITOR": 1, "REVIEW": 2, "DETERIORATING": 3, "VIOLATED": 4}

_EVAL_SCHEMA = {
    "pillar_evaluations": [
        {
            "pillar_name": "",
            "status": "INTACT",
            "score": 75,
            "confidence": 70,
            "reason": "",
        }
    ],
    "overall_summary": "",
}

_SYSTEM = """You are an investment analyst evaluating whether a holding's investment thesis
remains intact. You receive the thesis pillars with defined metrics and thresholds, plus
current financial data.

For each pillar assign:
  status: INTACT (condition holds), WEAKENED (showing strain but not broken),
          or VIOLATED (condition clearly falsified)
  score: 0–100 (100 = fully intact, 0 = completely violated)
  confidence: 0–100 (based on data quality and recency; lower if data is missing)
  reason: 1–2 sentences referencing actual numbers where available

Return valid JSON matching the schema exactly. Use the exact pillar_name strings provided.
"""


def _format_pillar(pillar: dict, metrics: list[dict]) -> str:
    lines = [
        f"Pillar: {pillar['name']} "
        f"(importance: {pillar['importance']:.0f}%, "
        f"critical: {bool(pillar.get('critical'))})"
    ]
    if pillar.get("description"):
        lines.append(f"  Description: {pillar['description']}")
    for m in metrics:
        lines.append(f"  Metric: {m['metric_key']} (direction: {m['direction']})")
        for level in ("healthy", "warning", "violation"):
            rule = m.get(f"{level}_rule_json")
            if rule:
                lines.append(f"    {level.title()}: {rule}")
        if m.get("persistence_periods", 1) > 1:
            lines.append(f"    Persistence required: {m['persistence_periods']} periods")
    return "\n".join(lines)


def _llm_evaluate(ticker: str, thesis: dict, pillars: list[dict], metrics_by_pillar: dict) -> dict:
    """One LLM call evaluates all pillars for a single thesis."""
    financial_context = financials_fetcher.get_financial_summary(ticker)
    if not financial_context:
        financial_context = f"No financial data currently available for {ticker}."

    pillar_blocks = "\n\n".join(
        _format_pillar(p, metrics_by_pillar.get(p["id"], [])) for p in pillars
    )

    prompt = f"""{_SYSTEM}

Ticker: {ticker}
Thesis summary: {thesis.get('summary', '(no summary)')}
Conviction: {thesis.get('conviction', 'N/A')}/5
Portfolio role: {thesis.get('portfolio_role', 'N/A')}

PILLARS:
{pillar_blocks}

CURRENT FINANCIAL DATA:
{financial_context}

Return JSON with "pillar_evaluations" (one entry per pillar using exact pillar_name) and "overall_summary"."""

    return ollama_client.generate_structured(
        prompt=prompt,
        schema=_EVAL_SCHEMA,
        model="mlx-community/Qwen3.6-35B-A3B-4bit",
        temperature=0.2,
        num_predict=2000,
        thinking=False,
        retries=2,
    )


def _derive_overall_status(pillars: list[dict]) -> str:
    """Deterministically derive overall thesis status from per-pillar statuses."""
    if any(p.get("critical") and p.get("status") == "VIOLATED" for p in pillars):
        return "VIOLATED"
    if any(p.get("status") == "VIOLATED" for p in pillars):
        return "DETERIORATING"
    if any(p.get("critical") and p.get("status") == "WEAKENED" for p in pillars):
        return "REVIEW"
    if any(p.get("status") == "WEAKENED" for p in pillars):
        return "MONITOR"
    return "INTACT"


def run_thesis_monitor(ctx: AgentContext) -> list[Recommendation]:
    recommendations: list[Recommendation] = []
    snapshot = ctx.snapshot

    # Earnings trigger: bypass the 45-day financials cache for the affected ticker
    if ctx.trigger_type == "earnings" and ctx.ticker:
        print(f"[thesis_monitor] Earnings trigger for {ctx.ticker} — bypassing 45-day cache")
        financials_fetcher.fetch_all([ctx.ticker], force=True)

    # Scope: specific ticker (earnings trigger) or all holdings (daily sweep)
    tickers = (
        [ctx.ticker]
        if ctx.ticker
        else [h.ticker for h in snapshot.holdings]
    )

    for ticker in tickers:
        thesis = agent_db.get_active_thesis(ticker)
        if not thesis:
            continue

        pillars = thesis.get("pillars", [])
        if not pillars:
            continue

        metrics_by_pillar = {
            p["id"]: agent_db.get_thesis_metrics(p["id"]) for p in pillars
        }

        try:
            result = _llm_evaluate(ticker, thesis, pillars, metrics_by_pillar)
        except Exception as e:
            print(f"[thesis_monitor] LLM eval failed for {ticker}: {e}")
            agent_db.insert_finding(
                run_id=ctx.run_id,
                finding_type="thesis_eval_error",
                summary=f"LLM evaluation failed for {ticker}: {e}",
                ticker=ticker,
                severity=0,
                confidence=0,
            )
            continue

        eval_by_name = {e["pillar_name"]: e for e in result.get("pillar_evaluations", [])}

        updated_pillars = []
        for pillar in pillars:
            ev = eval_by_name.get(pillar["name"], {})
            status = ev.get("status", "INTACT")
            if status not in _VALID_PILLAR_STATUSES:
                status = "INTACT"
            score = float(ev.get("score", 75))
            confidence = float(ev.get("confidence", 50))
            reason = ev.get("reason", "")

            agent_db.update_pillar_status(pillar["id"], status, score, confidence, reason)
            updated_pillars.append({**pillar, "status": status, "score": score, "confidence": confidence})

        overall = _derive_overall_status(updated_pillars)
        overall_summary = result.get("overall_summary", "")

        agent_db.insert_finding(
            run_id=ctx.run_id,
            finding_type="thesis_evaluation",
            summary=f"{ticker} thesis status: {overall}. {overall_summary}",
            ticker=ticker,
            severity=_STATUS_RANK.get(overall, 0) * 25,
            confidence=70,
        )
        print(f"[thesis_monitor] {ticker}: {overall} — {overall_summary[:80]}")

        if overall not in _PRIORITY:
            continue

        weak = [p for p in updated_pillars if p.get("status") in ("WEAKENED", "VIOLATED")]
        evidence = EvidenceBundle(
            has_price=True,
            financial_quarters=4,
            has_strategy_metadata=True,
            has_recent_fundamentals=True,
            source_quality="primary_corporate",
        )
        recommendations.append(Recommendation(
            ticker=ticker,
            action="REVIEW_THESIS",
            recommendation_score=_STATUS_RANK[overall] * 25,
            confidence=calculate_confidence(evidence),
            priority=_PRIORITY[overall],
            why_now=f"Thesis evaluation: {overall}. {overall_summary}",
            rationale=(
                "Affected pillars: "
                + ", ".join(f"{p['name']} ({p['status']})" for p in weak)
            ),
            counter_case="Monitor closely — one or more thesis pillars showing strain.",
            action_payload={
                "thesis_id": thesis["id"],
                "overall_status": overall,
                "pillar_statuses": [
                    {"name": p["name"], "status": p.get("status"), "score": p.get("score")}
                    for p in updated_pillars
                ],
            },
        ))

    return recommendations


register_agent("thesis_monitor", run_thesis_monitor)
