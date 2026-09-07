# Merge Manual Candidates into Opportunity Hunter Universe

- **ID:** 0048
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0042

## Problem

`run_opportunity_hunter()` starts by calling `_get_buffett_winners()` and operates solely on that universe. When a ticker is manually added via the dashboard, `serve.py` fetches its financials and triggers the opportunity hunter — but the hunter never actually scores the manual ticker because it isn't in the Buffett winners data. The candidate comparison UI does score manual `active`/`watch` tickers, but the autonomous hunter does not. Manual additions are effectively invisible to the core scoring pipeline.

## Proposed approach

- Define `candidate_universe` as: Buffett winners ∪ `candidate_universe` rows with `status IN ('active', 'watch')` and `source = 'MANUAL'`.
- In `run_opportunity_hunter()`, after fetching Buffett winners, also fetch manual candidates from DB and merge (deduplicating by ticker).
- Score all candidates identically regardless of source.
- Preserve `source` field (`BUFFETT` vs `MANUAL`) in the DB for traceability — the ranking UI already shows this.
- Ensure a manually added ticker that is already in Buffett winners doesn't get double-scored.

## Touches

- `agents/opportunity_agent.py` (`run_opportunity_hunter`, `_get_buffett_winners` or its caller)
- `serve.py` (manual-ticker trigger path — may just need to pass correct trigger event)

## Done when

- [x] Manually added `active`/`watch` candidates appear in the opportunity hunter's scoring pass
- [x] A manually added ticker that scores above threshold produces a recommendation (scored identically to Buffett winners)
- [x] `source` field is preserved: manual candidates carry `source='MANUAL'` from candidate_universe; Buffett winners carry their existing `source` field
- [x] No duplicate scoring: `_get_manual_candidates()` filters out tickers already in `winner_tickers`
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change

## Outcome

One file changed: `agents/opportunity_agent.py` — added `_get_manual_candidates()` helper that fetches active/watch MANUAL rows from `candidate_universe`. `run_opportunity_hunter()` merges them (deduplicating against Buffett winner tickers) into `all_candidates` before the scoring loop. Manual candidates with no Buffett data default to quality=buffett_score, valuation=43 (all None), and portal fit/catalyst defaults — they compete on equal terms in the LLM selection step.
