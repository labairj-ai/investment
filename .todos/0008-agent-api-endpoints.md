# Add Agent REST API Endpoints to serve.py

- **ID:** 0008
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0004, 0005

## Problem

The dashboard currently has no way to fetch persistent agent recommendations, record user decisions (Accept/Reject/Defer), or trigger an agent run on demand. The existing `/api/ai/daily` endpoint returns a one-shot analysis; there is no concept of a recommendation queue, decision recording, or run history. These API endpoints are the interface between the agent backend and the Decision Queue UI.

## Proposed approach

Add to `serve.py`:

- `GET /api/agents/recommendations?status=open` — returns open recommendations sorted by priority desc. Includes critic verdict and confidence for each.
- `GET /api/agents/recommendations/{id}` — full detail for one recommendation (finding, evidence, critic review, action payload).
- `POST /api/agents/recommendations/{id}/decision` — body: `{decision, reason_code, notes}`. Writes to `user_decisions` table, updates recommendation status. Returns updated recommendation.
- `GET /api/agents/runs` — recent agent run history (agent_type, trigger, status, started_at, finished_at).
- `GET /api/agents/runs/{id}` — full run detail including input_snapshot_json and all findings.
- `POST /api/agents/run` — body: `{agent_type, ticker?}`. Triggers an on-demand agent run (queued via the same semaphore as scheduled runs). Returns run_id immediately; client polls `/api/agents/runs/{id}` for completion.

All endpoints return JSON. Authentication is whatever `serve.py` currently uses (none, as the optiplex deployment has Tailscale access control).

## Touches

`serve.py`, `agent_db.py`, `agents/orchestrator.py`

## Done when

- [x] All 6 endpoints exist and return valid JSON
- [x] `POST /api/agents/recommendations/{id}/decision` correctly writes to `user_decisions` and flips recommendation status
- [x] `POST /api/agents/run` queues a run without blocking the HTTP response
- [x] `GET /api/agents/recommendations?status=open` returns empty array (not 500) when no recommendations exist yet
- [x] QA (API): `curl` or `httpx` each of the 6 endpoints and confirm valid JSON responses. Specifically: `GET /api/agents/recommendations?status=open` must return `[]` (not 500) when no recs exist; `POST /api/agents/recommendations/{id}/decision` must flip status in DB. Show actual response bodies before checking this box.

