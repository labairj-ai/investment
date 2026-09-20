# Migrate episode_outcomes to Version-Aware Unique Constraint

- **ID:** 0372
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0369

## Problem

`episode_outcomes` has `UNIQUE(episode_id, horizon)`, which prevents `calendar_v1`
and `sessions_v2` rows from coexisting for the same episode+horizon pair. The 0369
labeler recognizes this and explicitly skips the sessions_v2 write whenever a
calendar_v1 row already exists for the same slot. This makes the two horizon
definitions mutually exclusive rather than parallel: whichever version matures first
wins the slot, which can depend on calendar geometry rather than intent. The claim in
the 0369 commit that both versions are "written alongside" each other is currently
false.

## Proposed approach

- Create `episode_outcomes_v2` with `UNIQUE(episode_id, horizon, horizon_definition_version)`
- `INSERT INTO episode_outcomes_v2 SELECT *, 'calendar_v1' FROM episode_outcomes` to backfill
  existing rows (they predate the version column and are all calendar_v1)
- `DROP TABLE episode_outcomes`
- `ALTER TABLE episode_outcomes_v2 RENAME TO episode_outcomes`
- Update `_already_labeled()` in `outcome_labeler.py` — the version-aware query already
  exists; remove the extra `_already_labeled(..., "calendar_v1")` guard added as a
  workaround in the sessions_v2 loop
- Update `_insert_outcome()` — `INSERT OR IGNORE` idempotency is now version-scoped

Open question: does anything else depend on the old 2-column uniqueness that would
break if two rows for the same (episode_id, horizon) can now exist?

## Touches

- `agent_db.py` — table migration in `_migrate_learning_episodes()`; update `_new_cols`
  comment noting the 3-column index replaces the old CREATE TABLE default
- `agents/learning/outcome_labeler.py` — remove the skip-if-calendar-exists guard in
  the sessions_v2 loop; `_already_labeled()` already version-aware
- `tests/test_outcome_labeler.py` — add test that calendar_v1 and sessions_v2 rows
  coexist for the same (episode_id, horizon)

## Done when

- [ ] `episode_outcomes` has `UNIQUE(episode_id, horizon, horizon_definition_version)`
- [ ] Existing rows backfilled as `calendar_v1` on migration (safe to re-run)
- [ ] `outcome_labeler.py` sessions_v2 loop no longer skips when calendar_v1 exists
- [ ] Test: two rows with same episode_id + horizon but different versions both insert
- [ ] `python -m pytest tests/` passes with no regressions
