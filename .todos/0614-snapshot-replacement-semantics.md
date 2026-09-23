# Distinguish Extraction Success from Failure, Replace on Success

- **ID:** 0614
- **Status:** backlog
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0610

## Problem

`persist_events()` deletes same-day events only for tickers present in `events_by_ticker`. When extraction succeeds but the model finds no structured event for a ticker, that ticker is absent from `events_by_ticker` and its prior same-day events are never cleared — the dashboard keeps showing a stale event that the current snapshot no longer supports. The root ambiguity is that an empty dict is returned both for successful-but-empty extraction and for complete extraction failure. Before calibration, event history must reflect actual repeated evidence, not persistence artifacts caused by which tickers happened to produce a non-empty result.

## Proposed approach

- **Return contract:** Modify `extract_events_llm()` to return an explicit extraction status alongside results — e.g. `{"_extraction_ok": True, "AAPL": [...], "MSFT": []}` — rather than a plain dict that conflates success with failure. `run_pipeline()` reads this flag before deciding whether to persist.
- **Replacement on success:** On successful extraction, pass the full set of input tickers (all tickers in the snapshot) to `persist_events()`. Delete same-day events for every input ticker, including those that produced an empty list. Only tickers with events get new rows inserted.
- **Degrade on failure:** On extraction failure, skip event deletion entirely, leave the previous valid state intact, and write a `status='degraded'` (or similar) indicator to `news_summaries` so the dashboard can surface the stale-data condition rather than silently showing old events.

## Touches

- `agents/news/intelligence.py` — `extract_events_llm()` return contract; `persist_events()` deletion scope (accepts full input ticker set); `run_pipeline()` extraction status branching
- `portfolio_ai.py` or `news_summaries` schema — degraded-refresh status field (may already exist)
- `tests/test_news_intelligence.py` — test that zero-event tickers on successful extraction clear prior same-day rows; test that extraction failure preserves prior rows and marks degraded

## Done when

- [ ] `extract_events_llm()` return value unambiguously distinguishes success (zero or more events) from failure
- [ ] On successful extraction, same-day events for all input-snapshot tickers are replaced, including tickers that produced zero events
- [ ] On extraction failure, prior same-day events are preserved and `news_summaries` (or equivalent) records a degraded status
- [ ] Tests cover both paths: success-with-zero-events clears stale rows; failure preserves them
