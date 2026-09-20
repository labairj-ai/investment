# Build Canonical Security Master to Replace Duplicate Fund Detection

- **ID:** 0486
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0476

## Problem

Fund classification has two diverging sources of truth: `_KNOWN_FUNDS` in `portfolio_ai.py` and `HOLDING_PROFILES` elsewhere. `_KNOWN_FUNDS` misses mutual funds already described as funds in `HOLDING_PROFILES` (VTSAX, VFIAX, VTMGX, FSPTX, VVIAX) and incorrectly includes MSTR (a company). This means fund-vs-company routing in the evidence model is unreliable, and fund exposure estimates have a silently weaker data-generating process than company scores.

## Proposed approach

- Create a `SECURITY_MASTER` dict (or small sqlite table) keyed by ticker with fields: `security_type` (company/etf/mutual_fund), `fund_family`, `index_tracked`, `sector`, `country`. Seed it from the union of `HOLDING_PROFILES` and the existing `_KNOWN_FUNDS` list.
- Remove `_KNOWN_FUNDS`; replace all call sites with a `is_fund(ticker)` helper that reads `SECURITY_MASTER`.
- Remove MSTR from fund classification; add all missing mutual funds.
- For funds, set all four per-dim evidence qualities to `"unsupported"` and add a `fund_note` explaining that constituent-derived exposure is not yet implemented.
- Open question: should `SECURITY_MASTER` live in code (dict) or in the sqlite DB as a user-editable table?

## Touches

- `portfolio_ai.py` — `_KNOWN_FUNDS`, `_fetch_company_evidence()`, `is_fund()` helper
- Possibly a new `security_master` table in `investment.db`

## Done when

- [ ] `_KNOWN_FUNDS` removed; single `is_fund()` helper used everywhere
- [ ] VTSAX, VFIAX, VTMGX, FSPTX, VVIAX classified as funds
- [ ] MSTR classified as company
- [ ] All funds get `evidence_quality = "unsupported"` across all four dimensions
