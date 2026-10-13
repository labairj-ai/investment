# Complete Canonical NewsSnapshot Contract

- **ID:** 0601
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0596

## Problem

Four gaps remain after 0596. (a) `build_news_snapshot()` sets `model_input_text = body[:120] else excerpt[:80]` but the prose LLM still receives `body[:150] else excerpt[:100]`. A content change at characters 121–150 alters prose output without changing the cache hash, silently allowing stale summaries. (b) The snapshot hash payload is `(article_id, model_input_text)` without ticker. If the same article legitimately covers two holdings, the hash is unaffected by reassignment, breaking the invariant that hash == content seen by models. (c) The manifest is keyed globally by `article_id`, so when a single article covers two holdings (e.g. ANET and NVDA) one ticker overwrites the other, causing 0597's correct cross-ticker rejection to falsely discard the article for the second legitimate holder. (d) `decision_episodes.news_state` does not include `news_snapshot_hash`, so the third leg of the intended invariant (summaries hash == events hash == episode hash) is still missing.

## Proposed approach

- Raise `model_input_text` to `body[:150] else excerpt[:100]` (or have both prompt surfaces consume the snapshot's text directly) so hash and prompt input are always aligned.
- Include ticker in the snapshot hash payload; sort deterministically by `(ticker, article_id, model_input_text)`.
- Replace global `manifest[article_id]` keying with ticker-scoped `evidence_id = hash(ticker + article_id)` as the manifest key. Each `(ticker, article)` pair becomes a distinct entry; cross-ticker validation remains unambiguous even for shared articles.
- Add `news_snapshot_hash` to the JSON blob built by `_build_news_state()` in `episode_capture.py`.

## Touches

- `agents/news/intelligence.py` — `build_news_snapshot()`, `_build_article_manifest()`, `_build_event_extraction_prompt()`, `extract_events_llm()` (evidence_id keying throughout)
- `agents/learning/episode_capture.py` — `_build_news_state()`
- `tests/test_news_intelligence.py` — hash-covers-ticker test; shared-article accepted for both holdings; episode snapshot includes news_snapshot_hash

## Done when

- [x] `model_input_text` in snapshot matches the exact text passed to both event and prose LLMs
- [x] Body-only change at chars 121–150 invalidates the cache hash
- [x] Snapshot hash payload includes ticker; reassigning an article to a different holding changes the hash
- [x] An article covering two holdings produces two distinct manifest entries; both are accepted by 0597 validation
- [x] `decision_episodes.news_state` JSON includes `news_snapshot_hash` matching the canonical value
