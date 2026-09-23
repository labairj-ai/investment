# Evidence Provenance and Stable Event Identity

- **ID:** 0589
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0581

## Problem

Articles have no stable identity today. The LLM references events by title strings it hallucinated or paraphrased, so there is no way to trace a structured event back to the source article that caused it. If the same underlying story is covered by five outlets on the same day, `source_count` counts five independent events instead of one. The content hash covers only (ticker, title, source, pub_date), missing url and body, so hash collisions are possible. There is no tracking of when an event was first seen vs. last seen across daily refreshes — the same concern resets each run.

## Proposed approach

- Before calling the LLM, assign each article a deterministic `article_id = SHA256(url + source + pub_date + title)[:16]`. Pass the id alongside each article in the prompt.
- Instruct the LLM to populate `article_ids: [...]` on each extracted event using only IDs from the input manifest. Validate returned IDs against the manifest; drop any unrecognized IDs.
- Content hash expands to cover url + source + timestamp + title + excerpt/body.
- Persist `input_manifest_json` (list of `{article_id, ticker, title, source, pub_date, url}`) alongside the news_summaries row so provenance is always recoverable.
- Add `first_seen` and `last_seen` columns to `news_events`. On INSERT, check whether an event with the same `event_fingerprint` already exists for this ticker; if so, update `last_seen` and `source_count` rather than creating a duplicate row.
- `source_count` = number of distinct validated `article_ids` attached to an event, not raw article count.

## Touches

- `agents/news/intelligence.py` — `extract_events_llm()`, `compute_news_hash()`, `persist_events()`
- `portfolio_ai.py` — news_summaries INSERT to add `input_manifest_json` column
- DB schema — `news_events` table: add `article_ids_json`, `first_seen`, `last_seen`, `event_fingerprint` columns; `news_summaries` table: add `input_manifest_json` column

## Done when

- [ ] Every input article has a deterministic `article_id` before the LLM call
- [ ] LLM prompt instructs use of `article_ids` from the manifest; unrecognized IDs are rejected
- [ ] Content hash covers url + source + timestamp + title + excerpt
- [ ] `input_manifest_json` is persisted with the news_summaries row
- [ ] `first_seen` / `last_seen` track event persistence across daily runs without resetting
- [ ] `source_count` reflects distinct validated article IDs, not raw article count
