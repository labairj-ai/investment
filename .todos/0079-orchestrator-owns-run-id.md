# Let Orchestrator Own the agent_runs Row for On-Demand Runs

- **ID:** 0079
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

`POST /api/agents/run` in `serve.py` creates an `agent_runs` record itself (a wrapper run), then calls `orch.run_agents()` which creates additional `agent_runs` rows for each specialist. An on-demand request therefore produces at minimum two run records — one from the API handler, one from the orchestrator — and the API returns the wrapper ID rather than the actual specialist run IDs. This makes debugging the audit trail confusing.

## Proposed approach

- Remove the pre-created `agent_runs` row from `_handle_agent_run()` in `serve.py`.
- Have `run_agents()` return the list of `run_id` values it actually created, one per specialist agent that ran.
- The API response should return `{"run_ids": [...], "recommendation_count": N}`.
- For tracking async on-demand jobs, use a separate lightweight `async_jobs` table (job_id, requested_at, status, run_ids_json) rather than overloading `agent_runs`.
- Open question: is `async_jobs` worth adding now, or is just fixing the return value sufficient for the near term?

## Touches

- `serve.py` — `_handle_agent_run()` removes pre-insert, uses returned run_ids
- `agents/orchestrator.py` — `run_agents()` returns `list[int]` of run IDs
- `agent_db.py` — optionally add `async_jobs` table
- `tests/` — update any test that checks on-demand run behavior

## Done when

- [ ] `POST /api/agents/run` does not create a wrapper `agent_runs` row
- [ ] `run_agents()` returns the list of actual specialist run IDs
- [ ] API response includes the real run IDs
- [ ] An on-demand request for one agent produces exactly one `agent_runs` row per specialist that ran
