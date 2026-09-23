# Make Provenance Atomic, Identity Deterministic, and Corpus Queryable

- **ID:** 0613
- **Status:** backlog
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0610

## Problem

Three residual provenance gaps. (a) `_persist_snapshot()` commits independently before `persist_events()` — if snapshot persistence fails the pipeline silently continues, leaving `news_events` rows referencing a `snapshot_hash` with no provenance row. This contradicts the atomic provenance contract that 0610 was meant to establish. (b) `build_news_snapshot()` generates a random `uuid4()` as `snapshot_id`; if identical content is processed twice, `news_snapshots` retains the first random ID via `INSERT OR IGNORE` while other code carries the second, creating two identities for identical content. (c) The acceptance row in `_init_ai_tables()` hardcodes the prior commit SHA — by the time it is deployed the contract has already moved forward one commit. This one-behind pattern recurs every batch and the accepted corpus currently has no canonical query helper enforcing the boundary.

## Proposed approach

- **Atomic transaction:** Merge `_persist_snapshot()` and `persist_events()` into a single `BEGIN … COMMIT` block. If snapshot persistence fails, roll back and abort event persistence entirely. Optionally declare `REFERENCES news_snapshots(snapshot_hash)` on `news_events.news_snapshot_hash` with `PRAGMA foreign_keys = ON`.
- **Deterministic identity:** Replace `snapshot_id = uuid4()` in `build_news_snapshot()` with a deterministic derivation from the hash — either `uuid.uuid5(uuid.NAMESPACE_URL, snapshot_hash)` or simply use `snapshot_hash` directly as the identity. Same evidence bytes → same snapshot identity.
- **Runtime SHA:** Derive `accepted_commit` from the deployed git SHA at init time (`subprocess git rev-parse HEAD` or a `CODE_COMMIT_SHA` constant set at deploy). Never hardcode a prior commit.
- **Canonical helper:** Add `get_accepted_news_events(conn)` (or a SQL view) that enforces `extracted_at >= (SELECT MAX(accepted_at) FROM _news_intelligence_acceptance WHERE accepted_version='v2')`. All calibration/learning code must use this helper rather than querying `news_events` directly.

## Touches

- `agents/news/intelligence.py` — merge `_persist_snapshot` + `persist_events` + themes into one transaction; deterministic `snapshot_id` in `build_news_snapshot()`
- `portfolio_ai.py` — `_init_ai_tables()` runtime SHA for acceptance row; `get_accepted_news_events()` helper or view
- `tests/test_news_intelligence.py` — test snapshot-persist failure aborts event persist; test deterministic snapshot_id; test `get_accepted_news_events` filters pre-acceptance rows

## Done when

- [ ] If snapshot row cannot be written, `persist_events()` does not execute and the connection is rolled back
- [ ] Two calls to `build_news_snapshot()` with identical articles produce the same `snapshot_id`
- [ ] `_init_ai_tables()` derives `accepted_commit` from the deployed runtime SHA, not a hardcoded prior commit
- [ ] `get_accepted_news_events(conn)` exists and returns only rows with `extracted_at >= MAX(accepted_at)` for `accepted_version='v2'`
- [ ] All new behaviors covered by tests
