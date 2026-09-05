# Add LLM Inference Semaphore / Sequential Agent Queue

- **ID:** 0009
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0005

## Problem

The Mac Studio MLX endpoint runs one model at a time. If multiple agents fire concurrently (e.g., Guardian and CC Agent both triggered at 10am), parallel calls will queue at the server but may cause timeouts, garbled responses, or OOM under memory pressure. The system must serialize agent LLM calls through a single semaphore on the client side.

## Proposed approach

- Add `_llm_semaphore = threading.Semaphore(1)` in `agents/orchestrator.py`.
- `run_agents()` acquires the semaphore before each individual agent's LLM call and releases it after.
- Data collection (prices, news, macro) remains fully parallel via `ThreadPoolExecutor` as today — the semaphore only gates the model inference step, not I/O.
- Define a standard agent execution order: Guardian → CC → Thesis → Opportunity → Tax → Critic → Briefing.
- Agents with no triggers for the current snapshot are skipped entirely (zero model calls).
- Log when semaphore is acquired/released so it's auditable if an agent is slow.
- On-demand runs from `POST /api/agents/run` join the same queue — they don't bypass scheduled runs.

## Touches

`agents/orchestrator.py`, `agents/confidence.py` (may time out waiting — log that)

## Done when

- [ ] `_llm_semaphore` present in `orchestrator.py`
- [ ] `run_agents()` acquires semaphore per LLM call, not per agent (so data collection still parallelizes)
- [ ] Two concurrent `POST /api/agents/run` requests don't cause two simultaneous model calls
- [ ] Log lines show semaphore acquire/release timing
- [ ] QA (backend): Fire two concurrent `POST /api/agents/run` requests and check server logs to confirm the semaphore serializes LLM calls (only one model call active at a time, data collection still parallelizes). Show log lines with acquire/release timestamps before checking this box.

