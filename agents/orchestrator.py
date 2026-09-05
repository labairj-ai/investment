"""Agent orchestrator.

run_agents() is the single entry point for a full agent sweep. It:
  1. Acquires the LLM semaphore so only one agent calls the model at a time.
  2. Runs agents in canonical order, filtered to the triggered set.
  3. Writes results to agent_db.
  4. Returns the consolidated list of Recommendations.

Individual agent implementations are wired in as they are built (0006–0015).
"""
import threading

from .contracts import PortfolioSnapshot, Recommendation

# One LLM call at a time across all agents
_llm_semaphore = threading.Semaphore(1)

# Canonical execution order — Critic runs after producers; Briefing runs last
AGENT_ORDER = [
    "portfolio_guardian",
    "covered_call",
    "thesis_monitor",
    "opportunity_hunter",
    "tax",
    "sell_trim",
    "critic",
    "briefing",
]

# Registry: agent_type -> callable(context) -> list[Recommendation]
# Populated by each agent module via register_agent()
_registry: dict[str, object] = {}


def register_agent(agent_type: str, handler) -> None:
    """Register an agent handler. Called at import time by each agents/<name>.py."""
    _registry[agent_type] = handler


def run_agents(
    snapshot: PortfolioSnapshot,
    triggered_agents: list[str],
) -> list[Recommendation]:
    """Run triggered agents in canonical order and return all recommendations.

    Each registered agent is called with an AgentContext and must return a
    list[Recommendation]. Unregistered agent types are skipped with a warning.
    The LLM semaphore is acquired per-agent so inference calls are serialised.
    """
    import agent_db
    from .contracts import AgentContext
    from .triggers import TriggerEvent
    import time

    recommendations: list[Recommendation] = []
    to_run = [a for a in AGENT_ORDER if a in triggered_agents]

    for agent_type in to_run:
        handler = _registry.get(agent_type)
        if handler is None:
            # Agent not yet implemented — skip silently (expected during build-out)
            continue

        run_id = agent_db.insert_agent_run(agent_type=agent_type, scope="portfolio")
        try:
            with _llm_semaphore:
                ctx = AgentContext(
                    run_id=run_id,
                    snapshot=snapshot,
                    trigger_type="orchestrated",
                )
                agent_recs: list[Recommendation] = handler(ctx)

            for rec in agent_recs:
                agent_db.insert_recommendation(
                    ticker=rec.ticker,
                    action=rec.action,
                    run_id=run_id,
                    action_payload=rec.action_payload,
                    recommendation_score=rec.recommendation_score,
                    confidence=rec.confidence,
                    priority=rec.priority,
                    why_now=rec.why_now,
                    rationale=rec.rationale,
                    counter_case=rec.counter_case,
                    no_action_case=rec.no_action_case,
                    valid_until=rec.valid_until,
                )
            recommendations.extend(agent_recs)
            agent_db.finish_agent_run(run_id, status="done")
        except Exception as e:
            agent_db.finish_agent_run(run_id, status="error", error=str(e))
            print(f"[Orchestrator] {agent_type} failed: {e}")

    return recommendations
