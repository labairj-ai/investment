# News Intelligence Versioning and Episode Provenance

- **ID:** 0594
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0589, 0590, 0591

## Problem

`agents/news/intelligence.py` has `PROMPT_VERSION = "v1"` but no `NEWS_INTELLIGENCE_VERSION` constant. If the event taxonomy, thesis mapping logic, scoring weights, or trend semantics change, existing `news_events` rows and `decision_episodes.news_state` snapshots become silently incompatible with new rows. The learning corpus will mix two extraction generations without any way to filter or partition by generation. This is the same problem that required macro epoch discipline in the macro scoring system.

## Proposed approach

- Add `NEWS_INTELLIGENCE_VERSION = "v1"` to `agents/news/intelligence.py`. Bump this whenever extraction taxonomy, scoring formula, or trend semantics change materially. Same discipline as macro epochs: do not mix versions in learning queries without filtering.
- Freeze into `decision_episodes.news_state`: `news_intelligence_version`, `news_snapshot_hash`, `news_prompt_version`, `news_model_id`, `event_fingerprints` (list), `extracted_at`, `source_manifest_hash`.
- Add `news_intelligence_version TEXT` column to `news_events` table so each event row carries the version it was extracted under.
- `_build_news_state()` in `episode_capture.py` includes the version fields in the snapshot JSON.
- Document the epoch boundary discipline: any model, taxonomy, or formula change = new version string; old episode data is read-only under the prior version.

## Touches

- `agents/news/intelligence.py` — add `NEWS_INTELLIGENCE_VERSION` constant; stamp it on persisted events
- `agents/learning/episode_capture.py` — `_build_news_state()` snapshot includes version fields
- DB schema — `news_events`: add `news_intelligence_version TEXT`; `decision_episodes.news_state` JSON extended (no schema change needed, it is TEXT)

## Done when

- [ ] `NEWS_INTELLIGENCE_VERSION = "v1"` constant exists in `intelligence.py`
- [ ] Every `news_events` INSERT stamps `news_intelligence_version`
- [ ] `decision_episodes.news_state` JSON includes `news_intelligence_version`, `news_snapshot_hash`, `news_prompt_version`, `news_model_id`, `event_fingerprints`, `extracted_at`, `source_manifest_hash`
- [ ] Version bump procedure is documented in the file (one comment is enough)
- [ ] No query in the learning pipeline mixes events from different intelligence versions without a WHERE filter
