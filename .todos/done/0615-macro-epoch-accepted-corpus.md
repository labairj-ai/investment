# Fix Macro Epoch Timezone and Accepted-Corpus Boundary

- **ID:** 0615
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0612, 0613

## Problem

Two corpus-cleanliness gaps. (a) `holding_macro_scores_history.scored_at` is written with `datetime.now()` (local time) while news snapshot timestamps use UTC. `_get_macro_score()` compares them as plain text strings — a macro score written at 12:30 ET satisfies `scored_at <= "13:00"` UTC and can appear to predate a snapshot from 09:00 ET (actually 3.5 hours later). This is a real look-ahead leak. (b) The `_news_intelligence_acceptance` id=2 row uses `INSERT OR IGNORE`, so on existing production databases the row already exists with `accepted_commit=c5053fb` and `CODE_COMMIT_SHA` never lands. `get_accepted_news_events()` can therefore return observations produced under pre-dcdefc2 behavior, defeating the purpose of the acceptance boundary.

## Proposed approach

- **Macro epoch:** Add `scored_at_epoch REAL` column to `holding_macro_scores_history` via `ALTER TABLE … ADD COLUMN` migration. Populate it with `time.time()` whenever a macro score history row is written. In `_get_macro_score()`, convert `snapshot_captured_at` to Unix via `_iso_to_unix()` and compare `scored_at_epoch <= snapshot_epoch`. For rows missing `scored_at_epoch` (pre-migration), fail closed: return `{}` rather than falling back to text comparison.
- **Append-only acceptance:** Replace the fixed-id `INSERT OR IGNORE` seeding with a standalone `register_news_intelligence_acceptance()` function that inserts with no fixed id (SQLite auto-increment), records `accepted_commit=CODE_COMMIT_SHA`, `accepted_at=UTC now`, `accepted_version`, and notes. Never call it from `_init_ai_tables()` — only call it explicitly after deployment and canary validation. The schema migration in `_init_ai_tables()` still creates the table; the seeding is removed.
- **`get_accepted_news_events()` upgrade:** Filter by `extracted_at >= (SELECT MAX(accepted_at) FROM … WHERE accepted_version='v2' ORDER BY accepted_at DESC, id DESC LIMIT 1)`; require `news_intelligence_version = accepted_version`; require `news_snapshot_hash IN (SELECT snapshot_hash FROM news_snapshots)` to exclude events with missing provenance.

## Touches

- `portfolio_ai.py` — `_init_ai_tables()` migration for `scored_at_epoch`; remove fixed-id acceptance seeding; add `register_news_intelligence_acceptance()`; update `get_accepted_news_events()`
- Wherever `holding_macro_scores_history` rows are written (e.g. `generate_holding_macro_scores()`) — populate `scored_at_epoch`
- `agents/news/intelligence.py` — `_get_macro_score()` epoch comparison; fail-closed on missing epoch
- `tests/test_news_intelligence.py` and portfolio_ai tests — cover epoch comparison, fail-closed behavior, acceptance registration, and filtered corpus helper

## Done when

- [x] `holding_macro_scores_history` has `scored_at_epoch REAL`; all new rows populate it with `time.time()`
- [x] `_get_macro_score()` compares epochs; returns `{}` (no vote) for rows missing `scored_at_epoch`
- [x] `register_news_intelligence_acceptance()` exists, inserts with auto-id, records runtime SHA
- [x] `_init_ai_tables()` no longer seeds fixed-id acceptance rows (table creation only)
- [x] `get_accepted_news_events()` requires matching version and valid snapshot provenance
- [x] Test: macro score written after snapshot in local time cannot vote for that snapshot
- [x] Test: `get_accepted_news_events()` excludes events with no `news_snapshots` row

## Outcome

`_get_macro_score()` now requires `scored_at_epoch IS NOT NULL AND scored_at_epoch <= snap_epoch`; pre-migration rows fail closed. Both history INSERT sites in `generate_holding_macro_scores()` populate `scored_at_epoch=time.time()`. Fixed-id acceptance seeding removed from `_init_ai_tables()`; `register_news_intelligence_acceptance()` is the only write path. `get_accepted_news_events()` adds snapshot-provenance filter. 1576 tests passing (commit 2bddb8a).
