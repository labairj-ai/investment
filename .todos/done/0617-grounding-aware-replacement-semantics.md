# Add Per-Ticker Grounding Diagnostics and Replacement Semantics

- **ID:** 0617
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0614

## Problem

`extract_events_llm()` returns `_extraction_ok=True` whenever JSON parses correctly, even if every candidate event for a ticker was rejected by fail-closed validation (unknown ticker, zero valid same-ticker article IDs, hallucinated evidence). `run_pipeline()` treats this as a legitimate zero-event extraction and clears the ticker's prior same-day events via `persist_events()`. This is wrong: the model may have seen a real event, produced a structurally valid response, but every `article_id` was hallucinated or cross-ticker. In that case the prior good state should be preserved, not deleted.

## Proposed approach

- **Extraction diagnostics:** In `extract_events_llm()`, track per-ticker: `candidate_count` (raw events from model for ticker), `accepted_count` (passed validation), `rejected_count` (failed), `rejection_reasons` (list of strings). Return these alongside the event data.
- **Per-ticker classification:** After extraction, classify each ticker as:
  - `VALID_EVENTS` — `accepted_count > 0`
  - `VALID_EMPTY` — model returned no candidates for this ticker (`candidate_count == 0`)
  - `INVALID_EXTRACTION` — `candidate_count > 0` but `accepted_count == 0` (all candidates rejected by grounding)
- **Scoped replacement:** In `run_pipeline()` / `persist_events()`, pass only `VALID_EVENTS` and `VALID_EMPTY` tickers as `input_tickers` (the replacement-eligible set). `INVALID_EXTRACTION` tickers are excluded — their prior same-day events are retained untouched.
- **Degradation propagation:** Mark `INVALID_EXTRACTION` tickers as degraded in the pipeline result. Return a per-ticker degradation map so the dashboard can distinguish grounding failures from genuine empty-news days.

## Touches

- `agents/news/intelligence.py` — `extract_events_llm()` diagnostics; per-ticker classification logic; `persist_events()` `input_tickers` scoped to VALID tickers; `run_pipeline()` degradation result
- `tests/test_news_intelligence.py` — tests for: all-rejected ticker preserves prior events; VALID_EMPTY ticker clears prior events; INVALID_EXTRACTION ticker appears in degraded result; pipeline returns per-ticker grounding status

## Done when

- [x] `extract_events_llm()` returns `candidate_count`, `accepted_count`, `rejected_count`, `rejection_reasons` per ticker
- [x] Each ticker is classified as `VALID_EVENTS`, `VALID_EMPTY`, or `INVALID_EXTRACTION`
- [x] `persist_events()` only replaces same-day events for `VALID_EVENTS` and `VALID_EMPTY` tickers
- [x] `INVALID_EXTRACTION` tickers retain their prior same-day events after a pipeline run
- [x] `run_pipeline()` returns a per-ticker degradation map identifying grounding failures
- [x] Tests cover: all-rejected ticker keeps prior events; zero-candidate ticker clears prior events; degraded ticker count surfaces in pipeline result

## Outcome

`extract_events_llm()` tracks per-ticker diagnostics in `_ticker_diagnostics`. `run_pipeline()` classifies tickers into VALID_EVENTS / VALID_EMPTY / INVALID_EXTRACTION and passes only `valid_input_tickers` (VALID_EVENTS + VALID_EMPTY) to `persist_events()`. INVALID_EXTRACTION tickers are excluded from the deletion scope, preserving prior good state. `_grounding_degraded_tickers` returned on all paths. 1576 tests passing (commit 2bddb8a).
