# Canonical NewsSnapshot Contract

- **ID:** 0596
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0589

## Problem

`compute_news_hash()` runs before `enrich_with_bodies()` in `generate_news_summaries()`, so `news_summaries.news_snapshot_hash` is computed over un-enriched articles. `news_events.news_snapshot_hash` is computed inside `run_pipeline()` which runs after enrichment. The two hashes describe different inputs and can diverge silently. Additionally, `compute_news_hash()` covers only `(excerpt or body)[:80]`, but the event extraction prompt receives up to 120 chars and the prose prompt up to 150. A body change at characters 81–150 changes what the LLM sees while the cache hash remains unchanged, allowing stale cache hits.

## Proposed approach

- After `enrich_with_bodies()`, build one canonical `NewsSnapshot` object: `{snapshot_id, captured_at, articles: [{article_id, ticker, url, source, published_at, title, model_input_text, content_hash}], snapshot_hash}`.
- `model_input_text` is the exact normalized bytes supplied to the model (not a truncated approximation). Hash covers this full text.
- Pass the snapshot into `run_pipeline()` instead of the raw `by_ticker` dict.
- `news_summaries.news_snapshot_hash`, `news_events.news_snapshot_hash`, and `decision_episodes.news_state.news_snapshot_hash` must all carry the identical hash value from this single snapshot.
- Replace `compute_news_hash()` with `build_news_snapshot()` that returns the full structure.

## Touches

- `portfolio_ai.py` — `generate_news_summaries()` (move hash after enrichment, build snapshot)
- `agents/news/intelligence.py` — replace `compute_news_hash()` with `build_news_snapshot()`; update `run_pipeline()` signature
- `tests/test_news_intelligence.py` — add test: body-only change (no title/url/date change) must invalidate the cache hash

## Done when

- [x] `news_summaries.news_snapshot_hash` and `news_events.news_snapshot_hash` are always identical for the same generation run
- [x] Hash is computed after `enrich_with_bodies()`, not before
- [x] Hash covers the exact model input text, not a truncated approximation
- [x] Body-only change (no title/url/date) invalidates the cache hash (test passes)
- [x] `decision_episodes.news_state.news_snapshot_hash` matches the same canonical hash
