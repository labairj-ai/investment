# Merge Manual Candidates into Opportunity Hunter Universe

- **ID:** 0048
- **Status:** backlog
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

- [ ] Manually added `active`/`watch` candidates appear in the opportunity hunter's scoring pass
- [ ] A manually added ticker that scores above threshold produces a recommendation
- [ ] `source` field is preserved: manually added tickers show `MANUAL`, Buffett winners show `BUFFETT`
- [ ] No duplicate scoring for a ticker that appears in both Buffett winners and manual candidates
