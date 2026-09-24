from __future__ import annotations
"""
Briefing Agent — synthesizes portfolio brief state into a decision-oriented
action briefing and stores it as a BRIEFING recommendation.

Runs last in the pipeline (after all producers + Critic). Consumes the
Portfolio Brief State (0619) — a deterministic snapshot with no LLM calls —
and asks the LLM to synthesize priorities. No circular dependency on cached
AI insights.
"""

import json
import sqlite3
from collections import defaultdict
from datetime import date as _date, datetime as _dt

import agent_db
import ollama_client
from .contracts import AgentContext, Recommendation
from .orchestrator import register_agent

_PROMPT_VERSION = "briefing_v4"


def _build_brief_prompt(state: dict, date_str: str) -> str:
    """Build the LLM prompt for brief synthesis.

    The LLM produces ONLY headline, what_changed, and key_question.
    portfolio_state is computed deterministically by _apply_brief_policy — not by the LLM.
    needs_attention, opportunities, and watch come directly from brief_state.
    """
    lines = [f"PORTFOLIO DECISION BRIEF — {date_str}", ""]

    # Changes since last brief
    changes = state.get("changes", [])
    if changes:
        lines.append(f"CHANGED SINCE LAST BRIEF ({len(changes)} items):")
        for c in changes[:8]:
            ticker_part = f" [{c['ticker']}]" if c.get("ticker") else ""
            lines.append(f"  • [NEW]{ticker_part} {c.get('summary', '')[:120]}")
        lines.append("")

    # Attention items (context for LLM — it does NOT regenerate these)
    attention = state.get("attention_items", [])
    if attention:
        lines.append(f"NEEDS ATTENTION ({len(attention)} items — DO NOT reproduce, for context only):")
        for item in attention[:6]:
            new_tag = " [NEW]" if item.get("is_new") else ""
            ticker_part = f" [{item['ticker']}]" if item.get("ticker") else ""
            lines.append(f"  ⚠{new_tag}{ticker_part} {item.get('summary', '')[:120]}")
        lines.append("")

    # Opportunities (context only)
    opps = state.get("opportunities", [])
    if opps:
        lines.append(f"OPPORTUNITIES ({len(opps)} items — DO NOT reproduce, for context only):")
        for item in opps[:4]:
            new_tag = " [NEW]" if item.get("is_new") else ""
            ticker_part = f" [{item['ticker']}]" if item.get("ticker") else ""
            lines.append(f"  ↑{new_tag}{ticker_part} {item.get('summary', '')[:120]}")
        lines.append("")

    # Thesis health
    thesis = state.get("thesis_deltas", [])
    if thesis:
        lines.append("THESIS HEALTH:")
        for td in thesis:
            h = td.get("health_score")
            score_str = f"{h:.0f}/100" if h is not None else "?"
            violated = td.get("violated_pillars", [])
            warning = td.get("warning_pillars", [])
            line = f"  {td['ticker']}: {score_str}"
            if violated:
                line += f"  VIOLATED: {', '.join(violated)}"
            elif warning:
                line += f"  WARNING: {', '.join(warning)}"
            lines.append(line)
        lines.append("")

    # Critic summary
    cs = state.get("critic_summary", {})
    approved = cs.get("APPROVE", 0) + cs.get("APPROVE_WITH_CAUTION", 0)
    challenged = cs.get("CHALLENGE", 0)
    vetoed = cs.get("VETO", 0)
    if approved + challenged + vetoed > 0:
        lines.append(f"CRITIC: {approved} approved | {challenged} challenged | {vetoed} vetoed")
        lines.append("")

    # Capability state (learning, execution, macro)
    try:
        import portfolio_ai as _pai
        cap_summary = _pai._format_capability_summary(state)
        if cap_summary:
            lines.append(cap_summary)
            lines.append("")
    except Exception:
        pass

    # Freshness
    freshness = state.get("freshness", {})
    overall = freshness.get("overall", "UNKNOWN")
    lines.append(f"DATA FRESHNESS: {overall}")
    stale_sources = [k for k, v in freshness.items() if k != "overall" and v.get("is_stale")]
    if stale_sources:
        lines.append(f"  Stale sources: {', '.join(stale_sources)}")
    lines.append("")

    lines += [
        "Based on the portfolio state above, produce a concise decision-oriented narrative.",
        "Do NOT reproduce the attention/opportunity/watch lists — those are already shown to the user.",
        "Return ONLY this JSON (no markdown):",
        json.dumps({
            "headline": f"<1 sentence: overall portfolio state as of {date_str}>",
            "what_changed": ["<bullet: what is genuinely new since the last brief>"],
            "key_question": "<the single most important decision this portfolio faces today>",
        }, indent=2),
    ]

    return "\n".join(lines)


def _run_briefing_llm(brief_state: dict) -> dict:
    """Call the LLM with brief_state and return the narrative briefing dict.

    The LLM produces ONLY headline, what_changed, and key_question.
    portfolio_state is NOT produced here — it is computed deterministically by
    _apply_brief_policy after this call. Returns a dict with those three fields
    (plus a placeholder portfolio_state for _apply_brief_policy to normalize),
    or a deterministic fallback on failure.
    """
    date_str = _date.today().isoformat()

    attention = brief_state.get("attention_items", [])
    opps = brief_state.get("opportunities", [])
    total_items = len(attention) + len(opps) + len(brief_state.get("open_decisions", []))

    if total_items == 0 and not brief_state.get("changes"):
        # Absence of a brief_health key is not proof of health — treat as UNKNOWN.
        brief_health = brief_state.get("brief_health") or "UNKNOWN"
        if brief_health == "HEALTHY":
            return {
                "headline": "Portfolio stable — no material signals today.",
                "what_changed": [],
                "key_question": "No decisions required today.",
                "portfolio_state": "STABLE",
            }
        # Degraded/errored subsystems — STABLE is not a valid conclusion.
        degraded_subs = brief_state.get("brief_health_detail", [brief_health])
        sub_list = ", ".join(degraded_subs) if degraded_subs else brief_health
        return {
            "headline": f"Portfolio health {brief_health} — {sub_list} unavailable; cannot assess.",
            "what_changed": [],
            "key_question": f"Investigate before acting: {sub_list}.",
            "portfolio_state": "UNKNOWN",
        }

    prompt = _build_brief_prompt(brief_state, date_str)

    schema = {
        "headline": "",
        "what_changed": [],
        "key_question": "",
    }

    try:
        result = ollama_client.generate_structured(
            prompt, schema,
            temperature=0.3, num_predict=600,
            _caller="briefing_v4",
        )
        if not isinstance(result, dict) or "headline" not in result:
            raise ValueError("schema mismatch")
        return result
    except Exception as e:
        print(f"[BriefingAgent] LLM failed: {e}")
        if any(a.get("severity") == "high" for a in attention):
            portfolio_state = "URGENT"
        elif attention:
            portfolio_state = "ATTENTION"
        else:
            # No deterministic evidence warrants STABLE; use UNKNOWN so the
            # enforcer (_enforce_brief_health) has a safe default to work with.
            portfolio_state = "UNKNOWN"
        return {
            "headline": f"{len(attention)} item(s) need attention — see below.",
            "what_changed": [c.get("summary", "")[:120] for c in brief_state.get("changes", [])[:4]],
            "key_question": "Review attention items below.",
            "portfolio_state": portfolio_state,
        }


def run_briefing_agent(ctx: AgentContext) -> list[Recommendation]:
    date_str = _date.today().isoformat()

    # Use create_portfolio_brief() — the single path that builds state, runs LLM,
    # and persists both ai_insights and portfolio_brief_provenance atomically.
    brief_id = None
    briefing_output = {}
    brief_state = {}
    try:
        import portfolio_ai as _pai
        _pai._init_ai_tables()
        brief_conn = sqlite3.connect(str(_pai.DB_PATH), timeout=10)
        brief_conn.row_factory = sqlite3.Row
        result = _pai.create_portfolio_brief(brief_conn)
        brief_conn.close()
        briefing_output = result["brief"]
        brief_id = result["brief_id"]
        brief_state = result["brief_state"]
    except Exception as e:
        print(f"[BriefingAgent] create_portfolio_brief failed: {e}")
        briefing_output = {"headline": "Brief generation failed.", "portfolio_state": "UNKNOWN",
                           "what_changed": [], "key_question": ""}
        brief_id = "unknown"
        brief_state = {"freshness": {"overall": "UNAVAILABLE"}}

    # Build BRIEFING recommendation summary for the pipeline record
    headline = briefing_output.get("headline", "Daily briefing complete.")
    n_attention = len(brief_state.get("attention_items", []))
    n_opps = len(brief_state.get("opportunities", []))
    portfolio_state = briefing_output.get("portfolio_state", "UNKNOWN")

    rationale = f"[{portfolio_state}] {headline}"
    why_now = (
        f"Brief ID: {brief_id}. "
        f"{n_attention} attention item(s), {n_opps} opportunity(ies). "
        f"Freshness: {brief_state.get('freshness', {}).get('overall', 'unknown')}."
    )

    return [
        Recommendation(
            ticker=None,
            action="BRIEFING",
            rationale=rationale,
            why_now=why_now,
            recommendation_score=0,
            confidence=100,
            priority="low",
        )
    ]


register_agent("briefing", run_briefing_agent)
