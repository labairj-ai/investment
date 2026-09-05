# Add Candidate Universe Table and Manual Candidate UI

- **ID:** 0021
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** normal
- **Depends:** 0004, 0005, 0008

## Problem

The Opportunity Hunter (0014) currently assumes Buffett screener winners are the only candidates. There is no mechanism for the user to manually add a ticker they've heard about and immediately trigger a full analysis pipeline on it. And there is no persistent table tracking the candidate universe — which tickers have been evaluated, when, from what source, and whether they were accepted/rejected/watching. Without this, the opportunity pipeline has no memory.

## Proposed approach

**New table: `candidate_universe`**

| Field | Purpose |
|---|---|
| ticker | Security identifier |
| source | `BUFFETT` or `MANUAL` |
| added_at | When first entered |
| buffett_score | Current Buffett screen composite score (null if MANUAL) |
| status | `active` / `rejected` / `watch` / `owned` (auto-set when ticker appears in holdings) |
| notes | Optional free-text |
| last_evaluated | Timestamp of last Opportunity Agent run |

- `owned` status auto-set when ticker is present in `holdings.csv` — prevents re-recommending things already held
- Buffett winners are automatically upserted on each screener run
- Rejected candidates are kept with status `rejected` so the system remembers not to re-surface them without new evidence

**Manual candidate addition UI (dashboard):**
- Simple text input + [+] button: `Add candidate [ INCY ] [+]`
- On submit: upsert into `candidate_universe` with `source=MANUAL`, immediately triggers:
  1. Fundamentals fetch (`financials_fetcher.fetch(ticker)`)
  2. Valuation analysis
  3. Portfolio fit calculation
  4. Macro context check
  5. Opportunity Agent run
  6. Critic pass
- Result surfaces in Decision Queue within the normal agent pipeline
- Does not permanently add ticker to a background scanning universe — only the `candidate_universe` table

**API endpoints needed:**
- `POST /api/candidates` — body: `{ticker, notes?}` — adds manual candidate, triggers pipeline
- `GET /api/candidates` — list all non-rejected active candidates with scores
- `POST /api/candidates/{ticker}/reject` — sets status=rejected with optional reason
- `POST /api/candidates/{ticker}/watch` — sets status=watch (follow but don't analyze yet)

## Touches

`candidate_universe` table (new, add to migration in 0004 or separate migration), `agents/opportunity_agent.py` (read from this table), `buffett_screener.py` (upsert results here), `serve.py` (new API endpoints), `generate_dashboard.py` (manual add UI)

## Done when

- [x] `candidate_universe` table exists with all fields
- [x] Buffett screener upserts winners into the table on each run
- [x] Tickers in `holdings.csv` auto-set to `owned` status
- [x] Manual add via UI triggers full analysis pipeline
- [x] Rejected candidates stay in table with status=rejected (not re-surfaced)
- [x] `GET /api/candidates` returns active candidates with current scores
- [x] Browser QA (mandatory — do not skip): Open the dashboard in a browser and verify: (a) zero JS console errors, (b) manual 'Add candidate' UI triggers the full analysis pipeline (confirm DB row with `active` status), (c) Buffett screener winners appear in the table after a screener run, (d) `owned` tickers show correct status. Do NOT check this box without completing live browser testing.

## Outcome

- `candidate_universe` table added to `agent_db.py` migration with ticker/source/added_at/buffett_score/status/notes/last_evaluated fields.
- Five DB helpers: `upsert_candidate`, `set_candidate_status`, `get_candidates`, `sync_owned_candidates`, `mark_candidate_evaluated`.
- `buffett_screener.py` upserts winners on each `_flush()` call; BUFFETT source preserves `rejected` status.
- `serve.py`: `GET /api/candidates` (auto-syncs owned), `POST /api/candidates` (upsert + async pipeline), `POST /api/candidates/{ticker}/reject`, `POST /api/candidates/{ticker}/watch`.
- `generate_dashboard.py`: "Candidate Universe" card with live table; "+ Track Candidate" collapsible form with immediate pipeline trigger and inline success message.
- **Bug fixed during implementation:** inner single-quote in JS string literal broke dashboard at line 6812; fixed by removing quotes from empty-state message.
- Browser QA passed: MSFT/GRMN from Buffett screener appear, GRMN=OWNED, NVDA added manually with pipeline triggered (status=active, last_evaluated set within seconds).
- Note for 0014 (Opportunity Hunter): `opportunity_hunter` agent is a no-op stub until 0014 is built — the `run_agents` call in the pipeline fires but produces no output yet.

