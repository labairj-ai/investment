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

_PROMPT_VERSION = "briefing_v3"


def _build_brief_prompt(state: dict, date_str: str) -> str:
    lines = [f"PORTFOLIO DECISION BRIEF — {date_str}", ""]

    # Changes since last brief
    changes = state.get("changes", [])
    if changes:
        lines.append(f"CHANGED SINCE LAST BRIEF ({len(changes)} items):")
        for c in changes[:8]:
            ticker_part = f" [{c['ticker']}]" if c.get("ticker") else ""
            lines.append(f"  • [NEW]{ticker_part} {c.get('summary', '')[:120]}")
        lines.append("")

    # Attention items
    attention = state.get("attention_items", [])
    if attention:
        lines.append(f"NEEDS ATTENTION ({len(attention)} items):")
        for item in attention[:6]:
            new_tag = " [NEW]" if item.get("is_new") else ""
            ticker_part = f" [{item['ticker']}]" if item.get("ticker") else ""
            lines.append(f"  ⚠{new_tag}{ticker_part} {item.get('summary', '')[:120]}")
            lines.append(f"    source: {item.get('source', 'unknown')} | verdict: {item.get('critic_verdict', 'N/A')}")
        lines.append("")

    # Opportunities
    opps = state.get("opportunities", [])
    if opps:
        lines.append(f"OPPORTUNITIES ({len(opps)} items):")
        for item in opps[:4]:
            new_tag = " [NEW]" if item.get("is_new") else ""
            ticker_part = f" [{item['ticker']}]" if item.get("ticker") else ""
            lines.append(f"  ↑{new_tag}{ticker_part} {item.get('summary', '')[:120]}")
        lines.append("")

    # Watch items (abbreviated)
    watch = state.get("watch_items", [])
    if watch:
        lines.append(f"WATCH / NO ACTION ({len(watch)} items — top 3):")
        for item in watch[:3]:
            ticker_part = f" [{item['ticker']}]" if item.get("ticker") else ""
            lines.append(f"  ·{ticker_part} {item.get('summary', '')[:100]}")
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

    # Freshness
    freshness = state.get("freshness", {})
    overall = freshness.get("overall", "UNKNOWN")
    lines.append(f"DATA FRESHNESS: {overall}")
    stale_sources = [k for k, v in freshness.items() if k != "overall" and v.get("is_stale")]
    if stale_sources:
        lines.append(f"  Stale sources: {', '.join(stale_sources)}")
    lines.append("")

    n_attention = len(attention)
    n_opps = len(opps)
    n_open = len(state.get("open_decisions", []))

    lines += [
        "Based on the portfolio state above, produce a decision-oriented briefing.",
        "New items are marked [NEW]. Separate risks from opportunities. Be specific and concise.",
        "Return ONLY this JSON (no markdown):",
        json.dumps({
            "headline": f"<1 sentence: overall portfolio state as of {date_str}>",
            "what_changed": ["<bullet: new item since last brief>"],
            "needs_attention": [
                {
                    "ticker": "<ticker or null>",
                    "signal_type": "<guardian_finding|recommendation|thesis_health|news_signal>",
                    "summary": "<1-2 sentences — specific and actionable>",
                    "source": "<subsystem>",
                    "link_tab": "<portfolio|decisions|thesis|covered-calls|news>",
                }
            ],
            "opportunities": [
                {
                    "ticker": "<ticker or null>",
                    "signal_type": "<signal type>",
                    "summary": "<1-2 sentences>",
                    "source": "<subsystem>",
                    "link_tab": "<tab>",
                }
            ],
            "watch": [
                {
                    "ticker": "<ticker or null>",
                    "signal_type": "<signal type>",
                    "summary": "<1 sentence>",
                }
            ],
            "key_question": f"<the single most important decision this portfolio faces today>",
            "portfolio_state": "<STABLE|ATTENTION|URGENT>",
            "source_refs": [],
        }, indent=2),
    ]

    return "\n".join(lines)


def _run_briefing_llm(brief_state: dict) -> dict:
    """Call the LLM with brief_state and return the structured briefing dict.

    This is the shared core used by both the pipeline agent and on-demand generation.
    Returns a dict with headline/what_changed/needs_attention/opportunities/watch/
    key_question/portfolio_state/source_refs, or an error dict on failure.
    """
    date_str = _date.today().isoformat()

    attention = brief_state.get("attention_items", [])
    opps = brief_state.get("opportunities", [])
    total_items = len(attention) + len(opps) + len(brief_state.get("open_decisions", []))

    if total_items == 0 and not brief_state.get("changes"):
        return {
            "headline": "Portfolio stable — no material signals today.",
            "what_changed": [],
            "needs_attention": [],
            "opportunities": [],
            "watch": [],
            "key_question": "No decisions required today.",
            "portfolio_state": "STABLE",
            "source_refs": [],
        }

    prompt = _build_brief_prompt(brief_state, date_str)

    schema = {
        "headline": "",
        "what_changed": [],
        "needs_attention": [],
        "opportunities": [],
        "watch": [],
        "key_question": "",
        "portfolio_state": "STABLE",
        "source_refs": [],
    }

    try:
        result = ollama_client.generate_structured(
            prompt, schema,
            temperature=0.3, num_predict=1200,
            _caller="briefing_v3",
        )
        if not isinstance(result, dict) or "headline" not in result:
            raise ValueError("schema mismatch")
        return result
    except Exception as e:
        print(f"[BriefingAgent] LLM failed: {e}")
        # Deterministic fallback from brief_state (no LLM needed)
        fallback_attention = [
            {"ticker": a.get("ticker"), "signal_type": a.get("signal_type"),
             "summary": a.get("summary", "")[:150], "source": a.get("source", ""),
             "link_tab": "portfolio"}
            for a in attention[:3]
        ]
        fallback_opps = [
            {"ticker": o.get("ticker"), "signal_type": o.get("signal_type"),
             "summary": o.get("summary", "")[:150], "source": o.get("source", ""),
             "link_tab": "portfolio"}
            for o in opps[:2]
        ]
        portfolio_state = "URGENT" if any(
            a.get("severity") == "high" for a in attention
        ) else ("ATTENTION" if attention else "STABLE")
        return {
            "headline": f"{len(attention)} item(s) need attention — see below.",
            "what_changed": [c.get("summary", "")[:120] for c in brief_state.get("changes", [])[:4]],
            "needs_attention": fallback_attention,
            "opportunities": fallback_opps,
            "watch": [],
            "key_question": "Review attention items below.",
            "portfolio_state": portfolio_state,
            "source_refs": [],
        }


def run_briefing_agent(ctx: AgentContext) -> list[Recommendation]:
    import time as _time
    import uuid

    date_str = _date.today().isoformat()

    # Build Portfolio Brief State (deterministic — no LLM)
    try:
        import portfolio_ai as _pai
        _pai._init_ai_tables()
        brief_conn = sqlite3.connect(str(_pai.DB_PATH), timeout=10)
        brief_conn.row_factory = sqlite3.Row
        brief_state = _pai.build_portfolio_brief_state(brief_conn)
    except Exception as e:
        print(f"[BriefingAgent] Could not build brief state: {e}")
        brief_state = {
            "captured_at": _dt.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "changes": [], "attention_items": [], "opportunities": [],
            "watch_items": [], "open_decisions": [], "thesis_deltas": [],
            "news_signals": [], "portfolio_risks": [],
            "critic_summary": {}, "learning_state": {}, "execution_state": {},
            "freshness": {"overall": "UNAVAILABLE"},
        }

    # LLM synthesis
    briefing_output = _run_briefing_llm(brief_state)

    # Persist briefing to ai_insights (so dashboard /api/ai/daily can serve it)
    try:
        import portfolio_ai as _pai
        now_str = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        if _pai.DB_PATH.exists():
            pers_conn = sqlite3.connect(str(_pai.DB_PATH), timeout=10)
            pers_conn.execute(
                "INSERT OR REPLACE INTO ai_insights (day, insight, generated_at) VALUES (?,?,?)",
                (date_str, json.dumps(briefing_output), now_str),
            )
            pers_conn.commit()
            pers_conn.close()
    except Exception as e:
        print(f"[BriefingAgent] Could not persist to ai_insights: {e}")

    # Write provenance row (0623)
    brief_id = str(uuid.uuid4())
    try:
        import portfolio_ai as _pai
        if _pai.DB_PATH.exists():
            prov_conn = sqlite3.connect(str(_pai.DB_PATH), timeout=10)
            prov_conn.execute(
                "INSERT OR REPLACE INTO portfolio_brief_provenance "
                "(brief_id, captured_at, brief_snapshot_json, briefing_output_json, source_refs_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    brief_id,
                    brief_state.get("captured_at", now_str),
                    json.dumps(brief_state),
                    json.dumps(briefing_output),
                    json.dumps(briefing_output.get("source_refs", [])),
                ),
            )
            prov_conn.commit()
            prov_conn.close()
    except Exception as e:
        print(f"[BriefingAgent] Could not write provenance: {e}")

    # Build BRIEFING recommendation summary for the pipeline record
    headline = briefing_output.get("headline", "Daily briefing complete.")
    n_attention = len(briefing_output.get("needs_attention", []))
    n_opps = len(briefing_output.get("opportunities", []))
    portfolio_state = briefing_output.get("portfolio_state", "STABLE")

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
