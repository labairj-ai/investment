from __future__ import annotations
"""Agent orchestrator.

run_agents() is the single entry point for a full agent sweep. It:
  1. Runs agents in canonical order, filtered to the triggered set.
  2. Writes results to agent_db.
  3. Returns the consolidated list of Recommendations.

LLM serialisation is handled transparently: _install_llm_semaphore() wraps
ollama_client.generate_structured at import time so every model call from any
agent acquires _llm_semaphore first. Data collection (DB reads, yfinance I/O)
is never blocked — only the inference step is gated.

Individual agent implementations are wired in as they are built (0006–0015).
"""
import threading
import time as _time

from .contracts import PortfolioSnapshot, Recommendation

# One model inference at a time across all agents and threads.
_llm_semaphore = threading.Semaphore(1)
_semaphore_installed = False


def _install_llm_semaphore() -> None:
    """Wrap ollama_client.generate_structured with _llm_semaphore (once only).

    After this runs, every call to generate_structured — regardless of which
    agent or thread makes it — serialises through the semaphore. Data collection
    (DB reads, I/O) that doesn't touch the model is unaffected.
    """
    global _semaphore_installed
    if _semaphore_installed:
        return
    _semaphore_installed = True

    import ollama_client

    _orig = ollama_client.generate_structured

    def _wrapped(prompt, schema, **kwargs):
        t0 = _time.monotonic()
        caller = kwargs.pop("_caller", "agent")
        print(f"[LLM] {caller}: waiting for semaphore …")
        _llm_semaphore.acquire()
        wait_s = _time.monotonic() - t0
        print(f"[LLM] {caller}: semaphore acquired (waited {wait_s:.1f}s)")
        try:
            return _orig(prompt, schema, **kwargs)
        finally:
            elapsed = _time.monotonic() - t0
            _llm_semaphore.release()
            print(f"[LLM] {caller}: semaphore released (total {elapsed:.1f}s)")

    ollama_client.generate_structured = _wrapped


_install_llm_semaphore()


# Agents that iterate over portfolio holdings — NO_ACTION recorded for
# any holding they evaluated but did not flag.
_HOLDING_SCOPE_AGENTS = {"portfolio_guardian", "thesis_monitor", "covered_call", "tax"}


def _record_no_actions(
    agent_type: str,
    snapshot: PortfolioSnapshot,
    recommended_tickers: set[str],
    run_id: int,
) -> None:
    """Write NO_ACTION rows for holdings the agent evaluated but did not flag."""
    import agent_db

    for holding in snapshot.holdings:
        if holding.ticker in recommended_tickers:
            continue
        thesis_ver = agent_db._get_thesis_version_for_hash(holding.ticker)
        latest_q   = agent_db._get_latest_quarter_for_hash(holding.ticker)
        h = agent_db.compute_input_hash(
            holding.ticker, agent_type,
            holding.current_price or 0,
            thesis_ver, latest_q,
        )
        agent_db.upsert_no_action(
            ticker=holding.ticker,
            agent_type=agent_type,
            run_id=run_id,
            input_hash=h,
        )


# Canonical producer order — Critic and Briefing are post-processing stages,
# not peers. They are NOT triggered by events; they run automatically after
# producers finish (see run_agents). Never add "critic" to a TriggerEvent.
AGENT_ORDER = [
    "portfolio_guardian",
    "covered_call",
    "thesis_monitor",
    "opportunity_hunter",
    "tax",
    "sell_trim",
]

# Post-processing stages that run after producers, in this order.
_PIPELINE_STAGES = ["critic", "briefing"]

# Registry: agent_type -> callable(context) -> list[Recommendation]
# Populated by each agent module via register_agent()
_registry: dict[str, object] = {}


def register_agent(agent_type: str, handler) -> None:
    """Register an agent handler. Called at import time by each agents/<name>.py."""
    _registry[agent_type] = handler


def _run_single_agent(
    agent_type: str,
    handler,
    snapshot: PortfolioSnapshot,
    events: list | None = None,
    trigger_type: str = "orchestrated",
    ticker: str | None = None,
) -> list["Recommendation"]:
    """Run one agent, write results to DB, return its Recommendation list."""
    import agent_db
    from .contracts import AgentContext

    import ollama_client

    agent_events = events or []
    primary_event = agent_events[0] if agent_events else None
    primary_trigger = primary_event.trigger_type if primary_event else trigger_type
    primary_key = primary_event.trigger_key if primary_event else ticker

    # Compact snapshot for audit trail (per-ticker when available, else portfolio summary)
    _holding = next((h for h in snapshot.holdings if h.ticker == ticker), None) if ticker else None

    # Pull prompt_version from the handler module if it defines _PROMPT_VERSION
    _prompt_ver: str | None = getattr(handler, "__module__", None)
    try:
        import importlib, sys as _sys
        mod = _sys.modules.get(_prompt_ver or "")
        if mod:
            _prompt_ver = getattr(mod, "_PROMPT_VERSION", None)
        else:
            _prompt_ver = None
    except Exception:
        _prompt_ver = None

    # Per-ticker input hash for deduplication audit
    _input_hash: str | None = None
    _thesis_ver: int = 0
    _latest_q: str = ""
    if ticker:
        _thesis_ver = agent_db._get_thesis_version_for_hash(ticker)
        _latest_q   = agent_db._get_latest_quarter_for_hash(ticker)
        _price      = _holding.current_price if _holding else 0
        _input_hash = agent_db.compute_input_hash(ticker, agent_type, _price, _thesis_ver, _latest_q)

    # 0078: richer input manifest for reproducibility audit
    _input_snap: dict | None = None
    if _holding:
        _input_snap = {
            "ticker": ticker,
            "price": _holding.current_price,
            "shares": _holding.shares,
            "weight_pct": _holding.weight_pct,
            "price_as_of": getattr(snapshot, "price_as_of", None),
            "thesis_version": _thesis_ver,
            "financial_period": _latest_q,
            "macro_as_of": getattr(snapshot, "macro_as_of", None),
            "financials_as_of": getattr(snapshot, "financials_as_of", None),
            "prompt_version": _prompt_ver,
            "model": ollama_client.get_model_id(),
        }
    else:
        _input_snap = {
            "total_value": snapshot.total_value,
            "n_holdings": len(snapshot.holdings),
            "price_as_of": getattr(snapshot, "price_as_of", None),
            "macro_as_of": getattr(snapshot, "macro_as_of", None),
            "financials_as_of": getattr(snapshot, "financials_as_of", None),
            "prompt_version": _prompt_ver,
            "model": ollama_client.get_model_id(),
        }

    run_id = agent_db.insert_agent_run(
        agent_type=agent_type,
        scope="ticker" if ticker else "portfolio",
        ticker=ticker,
        trigger_type=primary_trigger,
        trigger_key=primary_key,
        model=ollama_client.get_model_id(),
        prompt_version=_prompt_ver,
        input_hash=_input_hash,
        input_snapshot=_input_snap,
    )
    try:
        ctx = AgentContext(
            run_id=run_id,
            snapshot=snapshot,
            trigger_type=primary_trigger,
            ticker=ticker,
            trigger_events=agent_events,
        )
        agent_recs: list[Recommendation] = handler(ctx)

        if agent_type in _HOLDING_SCOPE_AGENTS and snapshot.holdings:
            recommended = {r.ticker for r in agent_recs}
            _record_no_actions(agent_type, snapshot, recommended, run_id)

        inserted: list[Recommendation] = []
        for rec in agent_recs:
            if rec.ticker and rec.action not in ("NO_ACTION", "NO_CALL"):
                if agent_db.has_recent_user_decision(rec.ticker, rec.action, cooldown_days=5):
                    print(f"[Orchestrator] {agent_type}/{rec.ticker}/{rec.action}: "
                          f"cooldown — user decided within 5 days, skipping")
                    continue
            rec_id = agent_db.insert_recommendation(
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
                rationale_class=rec.rationale_class,
                input_hash=rec.input_hash,
            )
            if rec.dependencies:
                agent_db.write_dependencies(rec_id, rec.dependencies)
            inserted.append(rec)

        agent_db.finish_agent_run(run_id, status="done")
        return inserted, run_id
    except Exception as e:
        agent_db.finish_agent_run(run_id, status="error", error=str(e))
        print(f"[Orchestrator] {agent_type} failed: {e}")
        return [], run_id


def run_agents(
    snapshot: PortfolioSnapshot,
    events: list,  # list[TriggerEvent]
) -> tuple[list[Recommendation], list[int]]:
    """Run triggered producer agents then automatically run Critic on their output.

    Pipeline:
      1. Run all producers (agents in AGENT_ORDER) that have triggering events.
         "critic" and "briefing" events are silently ignored — they are
         post-processing stages, not peer agents.
      2. After producers finish, auto-run Critic if it is registered and there are
         any open unreviewed recommendations in the DB.
      3. Run Briefing last, only if a "briefing" event is present.

    Each agent receives the full list of TriggerEvents for its type via
    AgentContext.trigger_events, so it knows exactly why it was called.
    LLM calls are serialised by the semaphore installed at module level.

    Returns (recommendations, all_run_ids) — 0079: orchestrator owns run ID.
    """
    import agent_db
    from collections import defaultdict

    _stage_set = set(_PIPELINE_STAGES)

    events_by_agent: dict[str, list] = defaultdict(list)
    for event in events:
        events_by_agent[event.agent_type].append(event)

    run_briefing = "briefing" in events_by_agent

    recommendations: list[Recommendation] = []
    all_run_ids: list[int] = []
    producers_ran: list[str] = []

    for agent_type in AGENT_ORDER:
        if agent_type not in events_by_agent:
            continue
        handler = _registry.get(agent_type)
        if handler is None:
            raise RuntimeError(f"Triggered agent {agent_type!r} has no registered handler")
        recs, run_id = _run_single_agent(agent_type, handler, snapshot, events=events_by_agent[agent_type])
        all_run_ids.append(run_id)
        recommendations.extend(recs)
        producers_ran.append(agent_type)

    # Auto-run Critic after producers if there are unreviewed open recommendations.
    if producers_ran:
        critic_handler = _registry.get("critic")
        if critic_handler:
            unreviewed = agent_db.list_open_unreviewed_recommendations()
            if unreviewed:
                print(f"[Orchestrator] Auto-running critic on {len(unreviewed)} unreviewed rec(s)")
                _, critic_run_id = _run_single_agent("critic", critic_handler, snapshot)
                all_run_ids.append(critic_run_id)

    # Briefing runs last, only when explicitly triggered.
    if run_briefing:
        briefing_handler = _registry.get("briefing")
        if briefing_handler:
            _, briefing_run_id = _run_single_agent("briefing", briefing_handler, snapshot)
            all_run_ids.append(briefing_run_id)

    return recommendations, all_run_ids
