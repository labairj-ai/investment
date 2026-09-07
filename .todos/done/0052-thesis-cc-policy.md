# Add Per-Thesis CC Policy (Strategy, Max Delta, Min OTM, Avoid Earnings)

- **ID:** 0052
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

The CC agent uses a single generic philosophy for all covered-call candidates regardless of the holding's investment thesis. A Compounder (L3) with high conviction should have a very different CC strategy than a Cash-Flow Engine (L2): different OTM requirements, delta limits, and earnings-avoidance rules. The thesis schema already has a place for this (or should — per 0053), but the CC agent doesn't read or apply it. Applying a one-size-fits-all approach to ANET vs SCHD vs EW will systematically under-serve or over-risk certain positions.

## Proposed approach

- Add a `cc_policy` JSON field to `investment_theses` (or a separate `thesis_cc_policy` table) with:
  - `strategy`: `UPSIDE_PRESERVATION` | `INCOME` | `NONE` (no calls allowed)
  - `max_preferred_delta`: float (e.g. 0.18 for upside preservation, 0.30 for income)
  - `minimum_otm_pct`: float (e.g. 12% for upside preservation)
  - `avoid_earnings`: bool
  - `preferred_dte_min` / `preferred_dte_max`: int (days)
- Update the CC agent to fetch this policy from the DB before selecting strikes/expiries.
- If no policy is set for a ticker, fall back to the current generic defaults.
- Expose the policy in the thesis intake UI so it can be set when creating/editing a thesis.

## Touches

- `agents/covered_call_agent.py` (fetch and apply per-ticker CC policy)
- `thesis_engine.py` (generate a CC policy section as part of thesis proposal)
- DB schema: add `cc_policy` column to `investment_theses` or new table
- `serve.py` / thesis intake UI (edit CC policy fields)

## Done when

- [x] `investment_theses.cc_policy` TEXT column added via migration
- [x] CC agent reads policy via `_get_cc_policy(ticker)` before processing contracts
- [x] UPSIDE_PRESERVATION filters to lower delta and higher OTM; INCOME uses generic defaults
- [x] `strategy: NONE` causes the CC agent to log and return [] immediately
- [x] Falls back to `_CC_POLICY_DEFAULTS` when no active thesis or cc_policy is NULL; no errors
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change

## Outcome

Two files changed:

- **`agent_db.py`**: Added `cc_policy TEXT` column to `investment_theses` via migration.
- **`agents/covered_call_agent.py`**: Added `_CC_POLICY_DEFAULTS` dict and `_get_cc_policy(ticker)` helper (reads active thesis cc_policy JSON, merges with defaults). In `_analyze_ticker()`: (1) strategy=NONE → return [] immediately; (2) avoid_earnings=True → veto if any AVOID event present (stricter than default all-must-be-AVOID); (3) after AVOID gate, filter recs_df by max_preferred_delta and minimum_otm_pct; fall back to unfiltered universe if policy leaves 0 contracts. thesis intake UI / serve.py edits not done (out of scope for this todo — policy can be set by SQL or future UI work).
