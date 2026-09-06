# Add Per-Thesis CC Policy (Strategy, Max Delta, Min OTM, Avoid Earnings)

- **ID:** 0052
- **Status:** backlog
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

- [ ] `investment_theses` or related table has a `cc_policy` field
- [ ] CC agent reads the policy for the ticker before selecting strikes
- [ ] ANET (UPSIDE_PRESERVATION) generates higher-OTM, lower-delta CC recommendations than SCHD (INCOME)
- [ ] A thesis with `strategy: NONE` causes the CC agent to skip the ticker
- [ ] Policy falls back to generic defaults when not set; no errors on tickers without a policy
