# Add Candidate Universe Table and Manual Candidate UI

- **ID:** 0021
- **Status:** backlog
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

- [ ] `candidate_universe` table exists with all fields
- [ ] Buffett screener upserts winners into the table on each run
- [ ] Tickers in `holdings.csv` auto-set to `owned` status
- [ ] Manual add via UI triggers full analysis pipeline
- [ ] Rejected candidates stay in table with status=rejected (not re-surfaced)
- [ ] `GET /api/candidates` returns active candidates with current scores
- [ ] Browser QA (mandatory — do not skip): Open the dashboard in a browser and verify: (a) zero JS console errors, (b) manual 'Add candidate' UI triggers the full analysis pipeline (confirm DB row with `active` status), (c) Buffett screener winners appear in the table after a screener run, (d) `owned` tickers show correct status. Do NOT check this box without completing live browser testing.

