# Atomic News Provenance and Correct v2 Acceptance Boundary

- **ID:** 0610
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0607

## Problem

Three gaps before the v2 observation period can officially start. (a) There is a race condition between `persist_events()` writing `news_events` (with `news_snapshot_hash`) and the later `news_summaries` write (with `snapshot_id`, `snapshot_captured_at`). `_build_news_state()` reads `news_snapshot_hash` from `news_events` but `snapshot_id`/`snapshot_captured_at` from `news_summaries WHERE day=today` — if events are persisted but the summary row is not yet updated, a Decision Episode freezes a mismatched pair. (b) The `_news_intelligence_acceptance` row records `accepted_commit='94e0575'`, but commit `c5053fb` materially changes the confirmation contract, maintenance behavior, and provenance. The boundary is on the wrong commit. Additionally, `accepted_at` uses `datetime.now()` (local time) while `news_events.extracted_at` uses UTC, making textual comparisons timezone-dependent. The existing row was inserted with `INSERT OR IGNORE` and will not self-correct. (c) The TODO status files for 0605, 0606, and 0607 still say `Status: backlog` on GitHub because the status-update edits were not committed.

## Proposed approach

- **Atomic provenance:** Add a `news_snapshots` table (`snapshot_hash TEXT PRIMARY KEY, snapshot_id TEXT, captured_at TEXT, version TEXT, manifest_json TEXT`) written once in `run_pipeline()`. `_build_news_state()` resolves `snapshot_id`/`captured_at` via `news_events.news_snapshot_hash → news_snapshots.snapshot_hash`, never by day.
- **Acceptance boundary:** Append a new immutable row to `_news_intelligence_acceptance` for `c5053fb` with `accepted_at` as UTC epoch (Unix timestamp or explicit UTC ISO) and `accepted_version='v2'`. Effectiveness queries must use `MAX(accepted_at) WHERE accepted_version='v2'` as the filter boundary, not the first row. The wrong `94e0575` row is harmless to leave in place.
- **TODO status fix:** Commit the status updates to `.todos/0605`, `.todos/0606`, `.todos/0607` that were applied locally but not pushed.

## Touches

- `agents/news/intelligence.py` — `run_pipeline()` writes to `news_snapshots`; `persist_events()` or snapshot write must be atomic with event rows
- `portfolio_ai.py` — `_init_ai_tables()`: add `news_snapshots` table; seed new `c5053fb` acceptance row with UTC timestamp
- `agents/learning/episode_capture.py` — `_build_news_state()`: resolve `snapshot_id`/`snapshot_captured_at` from `news_snapshots` via hash join, not from `news_summaries WHERE day`
- `tests/test_news_intelligence.py` — test `news_snapshots` is written by `run_pipeline()`; test `_build_news_state()` uses hash join; test new acceptance row has UTC timestamp
- `.todos/0605-news-maintenance-operationalization.md`, `.todos/0606-real-independent-confirmation-sources.md`, `.todos/0607-final-provenance-acceptance-boundary.md` — status → done

## Done when

- [ ] `news_snapshots` table exists, keyed by `snapshot_hash`, populated by `run_pipeline()`
- [ ] `_build_news_state()` resolves `snapshot_id`/`snapshot_captured_at` from `news_snapshots` via hash, not from `news_summaries WHERE day`
- [ ] `_news_intelligence_acceptance` has a row for `accepted_commit='c5053fb'` with UTC-basis `accepted_at`
- [ ] Effectiveness queries documented to use `MAX(accepted_at) WHERE accepted_version='v2'`
- [ ] `.todos/0605`, `0606`, `0607` show `Status: done` on GitHub
