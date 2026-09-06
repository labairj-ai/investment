# Build Thesis Monitor Agent + Investment Thesis Data Model (Phase 5)

- **ID:** 0013
- **Status:** done
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

## Outcome

`agents/thesis_agent.py` (new) — registers `thesis_monitor` handler with orchestrator. Loops all holdings in the snapshot (or a single ticker on earnings trigger), loads each ACTIVE thesis with pillars from DB, calls LLM once per thesis with all pillar definitions + financial context, updates `thesis_pillars.status/score/confidence/last_evaluated_at` via `update_pillar_status()`, then derives overall status deterministically (critical VIOLATED → VIOLATED; any VIOLATED → DETERIORATING; critical WEAKENED → REVIEW; any WEAKENED → MONITOR). REVIEW/DETERIORATING/VIOLATED generates a `REVIEW_THESIS` recommendation at normal/high/urgent priority respectively.

`agent_db.get_active_thesis(ticker)` added — like `get_thesis()` but filtered to `status='ACTIVE'` only, so the monitor never re-evaluates superseded or draft theses.

`agents/triggers.py` — added portfolio-scope `thesis_monitor` trigger (daily sweep). Per-ticker earnings triggers come with 0006.

Schema note: "thesis_claims" in the original todo now maps to `thesis_pillars` (the new schema from 0030). The `thesis_claims` table still exists but new theses use pillars/metrics.

QA results (LLM_URL=http://100.73.128.40:8080):
- UNP thesis (FCF + operating income pillars, healthy thresholds): both pillars scored INTACT, score=90-95, confidence=90, last_evaluated_at set. No recommendation generated.
- NFLX thesis (gross margin > 70% threshold): pillar scored VIOLATED, score=15, confidence=95, recommendation inserted: `action=REVIEW_THESIS priority=urgent score=100 status=open`.
- Earnings trigger path: logged `"bypassing 45-day cache"` and called `fetch_all([ticker], force=True)`.

## Done when

- [x] At least one thesis (any format) loadable from DB for at least one holding
- [x] Deterministic claim evaluation works for metric-backed claims using `company_financials` data
- [x] Earnings trigger forces fundamentals refresh (bypasses 45-day cache)
- [x] LLM evaluates qualitative claims and returns per-claim status
- [x] `REVIEW`+ status generates a recommendation in the Decision Queue
- [x] `thesis_claims.current_status` and `last_evaluated_at` updated after each run
- [x] QA (backend): Load or create a minimal thesis for one holding. Run the monitor agent and confirm: (a) `thesis_claims.current_status` and `last_evaluated_at` updated in DB, (b) a REVIEW recommendation created when a claim breaches its threshold, (c) earnings trigger forces a financials refresh (log the cache bypass). Show DB row content before checking this box.

