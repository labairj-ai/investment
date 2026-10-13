# Touch updated_at for Unsupported Tickers in Score Run

- **ID:** 0690
- **Status:** done
- **Created:** 2026-09-26
- **Priority:** normal
- **Depends:** none

## Problem

Unsupported tickers (pre-revenue stocks like JOBY, funds, or tickers no longer held) are processed by `generate_holding_macro_scores()` but their `updated_at` in `holding_macro_scores` is never refreshed when the run classifies them as unsupported. After 5 days (`SCORE_STALE_DAYS`) they trigger `data_freshness: YELLOW` in the operational watchdog, requiring a manual SQL touch to silence. This recurs every 5 days indefinitely for every unsupported holding.

## Proposed approach

- In `generate_holding_macro_scores()`, after the batch loop, issue `UPDATE holding_macro_scores SET updated_at=now_utc_space() WHERE ticker=?` for each ticker that was processed but classified as unsupported (`evidence_quality == "unsupported"` or `is_fund`). No LLM call — timestamp touch only.
- Follow-on (separate todo): consider deleting rows from `holding_macro_scores` for tickers no longer present in the portfolio at all, rather than touching them forever.

## Touches

- `portfolio_ai.py` — `generate_holding_macro_scores()`

## Done when

- [x] Unsupported tickers get `updated_at` refreshed on every score run
- [x] `data_freshness` stays GREEN through weekends without manual intervention
- [x] No regression for supported tickers (scores, history, concordance logging unaffected)
