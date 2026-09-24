# Polish v2 Acceptance Layer Before Calibration Freeze

- **ID:** 0618
- **Status:** backlog
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0615, 0616, 0617

## Problem

Three small integration gaps remain before the v2 accepted corpus is safe to treat as a prospective calibration dataset. (1) `get_accepted_news_events()` does not enforce `news_intelligence_version = accepted_version`, so a future v3 run would pollute the v2 corpus query. (2) The cache-certification gate in `generate_news_summaries()` excludes extraction and persistence failures but not grounding degradation — a snapshot with INVALID_EXTRACTION tickers gets written to `news_summaries` as fully processed, blocking retries on the next same-hash refresh. (3) The extraction prompt tells the LLM to emit only tickers with real events, so an absent ticker in the output is inferred as VALID_EMPTY; this is indistinguishable from token truncation or the model accidentally skipping a ticker, which contaminates calibration data with false zero-event signals.

## Proposed approach

- **Version enforcement in `get_accepted_news_events(accepted_version='v2')`:** Look up the latest acceptance row for the requested version to get `(accepted_at, accepted_version)`. Filter events with:
  ```sql
  WHERE extracted_at >= ?
    AND news_intelligence_version = ?
    AND news_snapshot_hash IN (
        SELECT snapshot_hash FROM news_snapshots WHERE version = ?
    )
  ```
  Bind params are all sourced from the acceptance row, not hardcoded.

- **Grounding degradation blocks cache certification:** In `generate_news_summaries()`, add `bool(intel_result.get("_grounding_degraded_tickers"))` to the `_intel_degraded` condition. The prose response may still be returned to the caller; only the `news_summaries` INSERT is suppressed. Expose a lightweight indicator in the dashboard/API response, e.g. `"Structured intelligence partially degraded: GRMN — last valid events preserved."`.

- **Explicit ticker coverage in extraction prompt:** Change the prompt to require every input ticker in the JSON output — `{"ANET": [...], "GRMN": [], "SNA": []}`. Update the classification in `run_pipeline()` / `extract_events_llm()`: ticker present + `[]` → VALID_EMPTY; ticker present + events → validate normally; ticker absent entirely → INVALID_EXTRACTION. This makes completeness explicit rather than inferred.

- **Post-merge deployment action (not a code change):** After deploying 0618, run `register_news_intelligence_acceptance(accepted_version="v2", notes="News intelligence v2 prospective calibration start")` on the production DB. Verify the resulting row contains the runtime SHA for the deployed commit (2bddb8a or later) and a correct UTC `accepted_at`. Then freeze v2 — no further news-pipeline engineering todos.

## Touches

- `portfolio_ai.py` — `get_accepted_news_events()` version + snapshot-version enforcement; `generate_news_summaries()` grounding-degraded cache gate; dashboard degradation metadata in API response
- `agents/news/intelligence.py` — extraction prompt ticker-coverage requirement; absent-ticker → INVALID_EXTRACTION classification in `run_pipeline()` / `extract_events_llm()`
- `tests/test_news_intelligence.py` — version enforcement test; grounding-degraded cache-block test; absent-ticker INVALID_EXTRACTION test

## Done when

- [ ] `get_accepted_news_events(accepted_version='v2')` filters `news_intelligence_version = 'v2'` and `news_snapshots.version = 'v2'`
- [ ] A v3 event in the DB is excluded from a `get_accepted_news_events('v2')` call
- [ ] `bool(_grounding_degraded_tickers)` prevents `news_summaries` INSERT in `generate_news_summaries()`
- [ ] Dashboard/API response includes degradation indicator naming the affected tickers when grounding is partial
- [ ] Extraction prompt requires every input ticker; `[]` means VALID_EMPTY; absence means INVALID_EXTRACTION
- [ ] Test: LLM response omitting one input ticker classifies that ticker as INVALID_EXTRACTION
- [ ] All existing tests still pass
