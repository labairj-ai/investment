# Build Thesis Monitor Agent + Investment Thesis Data Model (Phase 5)

- **ID:** 0013
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0004, 0005, 0007, 0008

## Problem

The system knows "I own UNP" but not "why I own UNP." Without a recorded thesis, there is no way to detect when the reason for owning a position has weakened or been falsified. News, earnings changes, and macro shifts are evaluated in isolation rather than against the specific claims that justified the purchase. This is the biggest gap in the current system's analytical depth.

## Proposed approach

Two parts: the data model (already covered in 0004) and the agent.

**Thesis creation flow (manual + AI-assisted):**
- New API endpoint: `POST /api/theses/{ticker}` — user provides a summary and key claims; AI helps structure them.
- A claim has: text, optional `metric_key` (e.g., `free_cash_flow`), `operator` (e.g., `decline_yoy`), `threshold` (e.g., -20), `persistence_periods` (e.g., 2 quarters), `weight` (% of thesis confidence).
- Example falsifiable claim: "FCF remains healthy → metric: free_cash_flow, decline_yoy > -20%, persistence: 2 quarters."
- Dashboard UI: simple thesis creation form per holding. Low priority for the initial build — a JSON file per ticker in `data/theses/` is acceptable for v1.

**Thesis Monitor Agent** (`agents/thesis_agent.py`):

Triggered by: new earnings result, guidance revision, dividend cut (from trigger engine).

For each trigger, the agent:
1. Loads the holding's thesis from `investment_theses` / `thesis_claims`.
2. Checks each claim with deterministic metric conditions first (if `metric_key` is set, evaluate against `company_financials` table).
3. Forces fundamentals refresh if earnings event — don't rely on 45-day cache.
4. LLM evaluates non-deterministic claims (qualitative competitive moat, regulatory environment, etc.) and new news against the thesis claims.
5. Output per claim: `INTACT`, `WEAKENED`, `VIOLATED`.

LLM output:
```json
{
  "ticker": "UNP",
  "thesis_version": 3,
  "claim_evaluations": [
    {"claim_id": 1, "status": "WEAKENED", "evidence": "...", "severity": 45}
  ],
  "overall_status": "MONITOR",
  "summary": "...",
  "why_now": "..."
}
```

Overall statuses: `INTACT`, `MONITOR`, `REVIEW`, `DETERIORATING`, `VIOLATED`.

`REVIEW` and above generate a recommendation in the Decision Queue.

**Earnings-triggered refresh**: when a trigger fires due to earnings, call `financials_fetcher.fetch(ticker, force=True)` before the agent runs — bypass the 45-day cache for this ticker.

## Touches

`agents/thesis_agent.py` (new), `investment_theses` + `thesis_claims` tables (from 0004), `financials_fetcher.py` (add force refresh), `serve.py` (thesis CRUD endpoints), `generate_dashboard.py` (thesis creation UI — v2)

## Done when

- [ ] At least one thesis (any format) loadable from DB for at least one holding
- [ ] Deterministic claim evaluation works for metric-backed claims using `company_financials` data
- [ ] Earnings trigger forces fundamentals refresh (bypasses 45-day cache)
- [ ] LLM evaluates qualitative claims and returns per-claim status
- [ ] `REVIEW`+ status generates a recommendation in the Decision Queue
- [ ] `thesis_claims.current_status` and `last_evaluated_at` updated after each run
- [ ] QA evaluation conducted: functionality verified working, no regressions introduced

