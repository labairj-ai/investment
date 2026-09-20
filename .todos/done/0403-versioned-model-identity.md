# Include Horizon Version in Model ID and Isolate Null Observations

- **ID:** 0403
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** none

## Problem

Model version strings are currently `edge_v<cutoff>`, so two models trained against the same episode cutoff but different horizon versions (calendar_v1 vs sessions_v2) can collide on the same key. Models are stored as immutable INSERT-only rows, so a collision on the second save will silently fail or overwrite. Additionally, prospective evaluation queries accept observations where `target_horizon_version IS NULL`, meaning legacy pre-versioning rows can contaminate sessions_v2 model evaluations with outcomes from an unverified target definition.

## Proposed approach

- Change the model version format to include the horizon: `edge_<horizon>_<cutoff>` (e.g. `edge_sessions_v2_20260901`) or a fuller schema: `edge_<horizon>_<feature_schema>_<cutoff>`.
- Audit existing model rows and confirm no collision exists before deploying the new format.
- Write a one-time migration to backfill `target_horizon_version` on legacy NULL observation rows where the version can be inferred from the associated model record.
- After migration, remove the `OR target_horizon_version IS NULL` fallback from prospective evaluation queries for sessions_v2 models. Keep or mark the fallback for truly ambiguous rows that cannot be migrated.
- Open question: is `feature_schema` a meaningful component of the version key yet, or is that premature?

## Touches

- Model training / save logic (version string generation)
- Model storage schema or INSERT path
- Prospective evaluation query (remove NULL fallback)
- Migration script for legacy observation rows
- Any dashboard or promotion log that displays model version strings

## Done when

- [ ] Model version strings include the horizon version component
- [ ] Training calendar_v1 and sessions_v2 against the same cutoff produces two distinct version keys
- [ ] Legacy `target_horizon_version IS NULL` observation rows are migrated where possible
- [ ] Prospective evaluation for sessions_v2 models no longer includes NULL-target rows
- [ ] Existing model rows are not inadvertently overwritten by the new versioning scheme
