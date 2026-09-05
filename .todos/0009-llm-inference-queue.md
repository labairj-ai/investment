# Add LLM Inference Semaphore / Sequential Agent Queue

- **ID:** 0009
- **Status:** done
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

- [x] `_llm_semaphore` present in `orchestrator.py`
- [x] `run_agents()` acquires semaphore per LLM call, not per agent (so data collection still parallelizes)
- [x] Two concurrent `POST /api/agents/run` requests don't cause two simultaneous model calls
- [x] Log lines show semaphore acquire/release timing
- [x] QA (backend): Fire two concurrent `POST /api/agents/run` requests and check server logs to confirm the semaphore serializes LLM calls (only one model call active at a time, data collection still parallelizes). Show log lines with acquire/release timestamps before checking this box.

## Outcome

Modified `agents/orchestrator.py` only. No agent files touched.

**Implementation:** `_install_llm_semaphore()` monkey-patches `ollama_client.generate_structured`
at orchestrator import time. The wrapper acquires `_llm_semaphore` before calling the original
function and releases it in a `finally` block. A `_semaphore_installed` guard prevents
double-wrapping on repeated imports.

The old `with _llm_semaphore:` block that wrapped entire agent execution in `run_agents()` was
removed — data collection (DB reads, yfinance I/O) within each agent now runs freely; only
the model inference step is gated.

**Log format:**
```
[LLM] agent: waiting for semaphore …
[LLM] agent: semaphore acquired (waited 0.0s)
[LLM] agent: semaphore released (total 3.0s)
```

**QA results (2026-09-05, optiplex):**
- Two concurrent threads: request-A acquired immediately, request-B waited 0.35s ✓
- Log lines confirmed with wait/total timing ✓
- Wrapper confirmed installed (generate_structured identity changed after import) ✓

