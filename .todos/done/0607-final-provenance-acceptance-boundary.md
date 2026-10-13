# Persist Full Snapshot Manifest and Record Acceptance Boundary

- **ID:** 0607
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0601, 0602

## Problem

Two provenance gaps remain before observations can be used as a clean calibration corpus. (a) `news_summaries.input_manifest_json` is built from the pipeline `_manifest`, which retains ticker/article_id/title/source/pub_date/url but drops `model_input_text`, `content_hash`, `snapshot_id`, and `captured_at`. Without these fields it is impossible to reconstruct — from the DB alone — exactly what evidence produced a given `news_snapshot_hash`. The storage cost of persisting the full canonical manifest is trivial (150/100-char snippets per article). (b) `NEWS_INTELLIGENCE_VERSION='v2'` was introduced in e139df3 but the contract changed materially in 94e0575 (snapshot identity, evidence identity, confirmation semantics, state-maintenance). Any observations captured between those two commits carry the same label but a different contract. The learning system needs a crisp boundary to exclude pre-acceptance v2 rows from effectiveness analysis.

## Proposed approach

**(a) Full snapshot manifest persistence:**
- When `persist_events()` or the news-summaries cache write runs, store the full canonical snapshot manifest (keyed by evidence_id, value = `{article_id, ticker, model_input_text, content_hash, url}`) as `input_manifest_json` on `news_summaries`.
- Add `snapshot_id TEXT` and `snapshot_captured_at TEXT` columns to `news_summaries` (ALTER TABLE for existing DBs).
- Populate from `snapshot["snapshot_id"]` and `snapshot["captured_at"]` when writing the summary row.
- Update `_build_news_state()` in `episode_capture.py` to also include `snapshot_id` and `snapshot_captured_at` in the JSON blob.

**(b) Acceptance boundary:**
- Check the production DB for `news_events` rows with `news_intelligence_version='v2'` and `extracted_at < '94e0575 deploy timestamp'`. If trivially small (or zero), record only an acceptance marker; do not bump to v3.
- Add a `_news_intelligence_acceptance` table (or insert into existing `macro_acceptance_state`) with columns: `accepted_at`, `accepted_commit`, `accepted_version`, `notes`.
- Seed one row: `accepted_commit='94e0575'`, `accepted_version='v2'`, `accepted_at=<now on first run>`.
- Document in comments that learning queries must `WHERE extracted_at >= (SELECT accepted_at FROM _news_intelligence_acceptance WHERE accepted_version='v2' ORDER BY accepted_at DESC LIMIT 1)`.

## Touches

- `agents/news/intelligence.py` — `persist_events()` (store full manifest + snapshot_id/captured_at)
- `portfolio_ai.py` — `_init_ai_tables()` (ALTER for `news_summaries`; add `_news_intelligence_acceptance` table); `generate_news_summaries()` (pass snapshot_id/captured_at to summary write)
- `agents/learning/episode_capture.py` — `_build_news_state()` (add `snapshot_id`, `snapshot_captured_at`)
- `tests/test_news_intelligence.py` — news_summaries row carries full manifest + snapshot_id; acceptance table seeded on first `_init_ai_tables()` call

## Done when

- [ ] `news_summaries` rows include `snapshot_id`, `snapshot_captured_at`, and `input_manifest_json` containing `model_input_text` and `content_hash` per article
- [ ] `_build_news_state()` JSON includes `snapshot_id` and `snapshot_captured_at`
- [ ] `_news_intelligence_acceptance` table (or `macro_acceptance_state` row) records `accepted_commit=94e0575`, `accepted_version=v2`, `accepted_at`
- [ ] Acceptance row is seeded idempotently on `_init_ai_tables()` (INSERT OR IGNORE)
- [ ] Learning queries documented or enforced to exclude observations before `accepted_at`
