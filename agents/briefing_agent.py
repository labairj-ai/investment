"""
Briefing Agent — synthesizes today's specialist agent findings into an
action-oriented portfolio summary and stores it in the ai_insights cache.

Runs last in the pipeline (after all producers + Critic) so it can reference
what agents found and what the Critic approved or rejected. Returns a single
BRIEFING recommendation whose rationale is the plain-text summary.
"""

import portfolio_ai
from .contracts import AgentContext, Recommendation
from .orchestrator import register_agent


def run_briefing_agent(ctx: AgentContext) -> list[Recommendation]:
    insight = portfolio_ai.generate_daily_insight(force=True)

    if "error" in insight:
        print(f"[BriefingAgent] Insight generation failed: {insight['error']}")
        return []

    # Build a compact plain-text summary for the recommendation rationale.
    lines = []
    if insight.get("macro_summary"):
        lines.append(f"Macro: {insight['macro_summary']}")
    for flag in (insight.get("risk_flags") or []):
        lines.append(f"• {flag}")
    if insight.get("key_question"):
        lines.append(f"Key question: {insight['key_question']}")

    summary = "\n".join(lines) or "Daily briefing complete — no material findings."

    return [
        Recommendation(
            ticker=None,
            action="BRIEFING",
            rationale=summary,
            why_now="Daily portfolio synthesis after specialist agent pipeline run.",
            recommendation_score=0,
            confidence=1.0,
            priority="low",
        )
    ]


register_agent("briefing", run_briefing_agent)
