# Content-Address News Analysis to Fix Stale-Summary Problem

- **ID:** 0580
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** none

## Problem

`generate_news_summaries()` caches LLM analysis by calendar day. The browser fetches news at 6 AM / noon / 5 PM on a 30-minute TTL, meaning fresh noon headlines can be paired with AI analysis generated that morning. The user sees current articles but reads stale conclusions. There is no way to tell when the analysis was generated, which articles it was based on, or which model/prompt produced it.

## Proposed approach

- Compute a deterministic `news_snapshot_hash` from the set of article IDs, titles, sources, and timestamps used as LLM input. When the hash changes materially (e.g., new articles added above a configurable threshold), mark the cached analysis stale and trigger re-generation.
- Persist alongside each generated analysis: `generated_at`, `news_snapshot_hash`, `model_id`, `prompt_version`, and the list of `article_ids` used.
- Replace the day-keyed cache lookup with a hash-keyed lookup. Day-level dedup remains as a secondary guard against unnecessary LLM calls when no new articles have appeared since the prior run.
- Surface `generated_at` and article count in the dashboard tooltip/footer so staleness is visible.

## Touches

- `agents/news/generate_news_summaries.py` (or equivalent) — cache key logic
- DB schema — add columns to news analysis table
- Dashboard — expose `generated_at` and article count

## Done when

- [x] LLM analysis is re-run whenever the news snapshot hash changes materially, not only on the first call of the day
- [x] Each stored analysis record includes `generated_at`, `news_snapshot_hash`, `model_id`, `prompt_version`, and `article_ids`
- [x] Dashboard shows when the analysis was generated (not just the article date)
- [x] A same-day re-fetch that adds new articles triggers fresh analysis; a re-fetch with identical articles does not

## Outcome

`agents/news/intelligence.compute_news_hash()` computes a 16-char SHA256 over sorted (ticker, title, source, pub_date) tuples. `generate_news_summaries()` now fetches articles first, computes the hash, and calls `get_cached_news_summaries_today(news_snapshot_hash=hash)` — which returns None on hash mismatch, triggering regeneration. `news_summaries` table gained `news_snapshot_hash`, `model_id`, `prompt_version`, `article_count` columns. The `force=False` path checks hash; `force=True` skips cache but still hashes for storage.
