from __future__ import annotations
"""
Briefing Agent — synthesizes today's specialist agent findings into an
action-oriented portfolio summary and stores it as a BRIEFING recommendation.

Runs last in the pipeline (after all producers + Critic) and synthesizes:
  - agent_findings from all specialist agents (last 24h)
  - open recommendations grouped by agent and action
  - Critic verdicts (APPROVE / CHALLENGE / VETO counts)
  - Macro context from portfolio_ai (evidence only, not a full re-analysis)

The LLM receives this structured digest and produces a 2-3 sentence summary
of what matters today. This avoids re-deriving what the specialists already know.
"""

from collections import defaultdict

import agent_db
import ollama_client
from .contracts import AgentContext, Recommendation
from .orchestrator import register_agent

_PROMPT_VERSION = "briefing_v2"


def _build_briefing_prompt(
    findings: list[dict],
    recs: list[dict],
    critic_summary: dict,
    macro_context: str,
    date_str: str,
) -> str:
    # Group findings by agent_type
    by_agent: dict[str, list[dict]] = defaultdict(list)
    for f in findings:
        by_agent[f.get("agent_type", "unknown")].append(f)

    # Group recs by agent_type
    recs_by_agent: dict[str, list[dict]] = defaultdict(list)
    for r in recs:
        recs_by_agent[r.get("agent_type", "unknown")].append(r)

    lines = [f"PIPELINE SUMMARY — {date_str}", ""]

    agent_display = [
        ("portfolio_guardian", "PORTFOLIO GUARDIAN"),
        ("thesis_monitor",     "THESIS MONITOR"),
        ("sell_trim",          "SELL / TRIM"),
        ("covered_call",       "COVERED CALL"),
        ("opportunity_hunter", "OPPORTUNITY"),
        ("tax",                "TAX"),
    ]

    for key, label in agent_display:
        f_list = by_agent.get(key, [])
        r_list = recs_by_agent.get(key, [])
        count = len(f_list) + len(r_list)
        lines.append(f"{label}: {count} finding(s)")
        for f in f_list[:3]:
            ticker_part = f" [{f['ticker']}]" if f.get("ticker") else ""
            lines.append(f"  • {f['summary']}{ticker_part}")
        for r in r_list[:3]:
            ticker_part = f" [{r['ticker']}]" if r.get("ticker") else ""
            verdict_part = f" (critic: {r['critic_verdict']})" if r.get("critic_verdict") else ""
            lines.append(f"  → {r['action']}{ticker_part}{verdict_part}: {(r.get('rationale') or '')[:120]}")

    lines.append("")
    if critic_summary:
        approved   = critic_summary.get("APPROVE", 0) + critic_summary.get("APPROVE_WITH_CAUTION", 0)
        challenged = critic_summary.get("CHALLENGE", 0)
        vetoed     = critic_summary.get("VETO", 0)
        lines.append(f"CRITIC: {approved} approved | {challenged} challenged | {vetoed} vetoed")
        lines.append("")

    if macro_context:
        lines.append(f"MACRO CONTEXT: {macro_context[:400]}")
        lines.append("")

    lines += [
        "Based on the above specialist findings, identify the 2-3 most important things",
        "requiring the investor's attention today. Be concise and reference specific tickers.",
        "Return ONLY this JSON (no markdown):",
        '{"summary": "<2-3 sentence actionable briefing>", "key_tickers": ["TICK1", "TICK2"]}',
    ]

    return "\n".join(lines)


def run_briefing_agent(ctx: AgentContext) -> list[Recommendation]:
    from datetime import date as _date

    date_str = _date.today().isoformat()

    findings      = agent_db.get_todays_findings(window_hours=24)
    recs          = agent_db.get_todays_recommendations(window_hours=24)
    critic_summary = agent_db.get_todays_critic_summary(window_hours=24)

    # Macro context: use today's cached insight excerpt (not a full re-analysis)
    macro_context = ""
    try:
        import portfolio_ai as _pai
        cached_insight, _ = _pai.get_cached_insight_today()
        if cached_insight:
            macro_context = cached_insight.get("macro_summary") or ""
    except Exception:
        pass

    total_items = len(findings) + len(recs)
    if total_items == 0:
        summary = "No material findings from specialist agents today — portfolio monitoring complete."
        return [
            Recommendation(
                ticker=None,
                action="BRIEFING",
                rationale=summary,
                why_now="Daily portfolio synthesis — no actionable signals.",
                recommendation_score=0,
                confidence=100,
                priority="low",
            )
        ]

    prompt = _build_briefing_prompt(findings, recs, critic_summary, macro_context, date_str)

    schema = {"summary": "", "key_tickers": []}
    try:
        result = ollama_client.generate_structured(
            prompt, schema,
            temperature=0.3, num_predict=800,
            _caller="briefing",
        )
        summary = result.get("summary") or "Daily briefing complete."
    except Exception as e:
        print(f"[BriefingAgent] LLM failed: {e}")
        # Fallback: build summary from top findings
        top = (findings + recs)[:3]
        summary = "; ".join(
            (f.get("summary") or f.get("rationale") or "")[:100] for f in top
        ) or "Daily briefing complete — see specialist findings."

    return [
        Recommendation(
            ticker=None,
            action="BRIEFING",
            rationale=summary,
            why_now=f"Daily portfolio synthesis: {len(findings)} finding(s), {len(recs)} recommendation(s).",
            recommendation_score=0,
            confidence=100,
            priority="low",
        )
    ]


register_agent("briefing", run_briefing_agent)
