# Immutable Model Artifact Identity

- **ID:** 0409
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0403

## Problem

0403 fixed horizon-version collisions by including the horizon in the version string (`edge_sessions_v2_v<cutoff>`). But the version still depends only on horizon + training cutoff. Retraining after changing ridge lambda, feature schema, normalization, exclusion rules, or training code with the same cutoff date produces the same version string and silently overwrites or collides with the prior model. `feature_schema_hash` is already computed but not included in the version key.

## Proposed approach

Two complementary improvements:

1. **Short-term (minimal change)**: Include `feature_schema_hash` in the version string:
   `edge_{horizon}_{schema_hash[:8]}_v{cutoff}` — eliminates most practical collisions.

2. **Longer-term (proper registry)**:
   - Add an immutable `model_id` UUID column (PRIMARY KEY of new identity) separate from the human-readable `model_version` display string.
   - Store full training provenance: `training_cutoff`, `horizon_version`, `feature_schema_hash`, `training_config_hash` (hash of ridge_alpha + any relevant hyperparams), `code_commit_sha`.
   - `model_version` becomes a display label, not an identity key.
   - Foreign keys in `model_observations`, `model_performance_snapshots`, and promotion log use `model_id`.

Open question: is the schema-hash-in-version (option 1) sufficient for the current phase, or should the full registry be built now? Given 0404–0410 are already in flight, option 1 is the safer short-term step.

## Touches

- `agents/learning/calibration.py` — `ChallengerModel.train()` version string generation, `save()`
- `agent_db.py` — migration to add `model_id` column, update schema if going with option 2
- `model_observations`, `model_performance_snapshots` — FK update if option 2
- Tests — same-cutoff retrain with different schema_hash must produce distinct versions

## Done when

- [ ] `feature_schema_hash` (first 8 chars) is included in the model version string
- [ ] Retraining after a feature schema change with same cutoff produces a distinct version
- [ ] Existing test for distinct calendar_v1 vs sessions_v2 versions still passes
- [ ] Decision on model_id UUID (option 2) is documented as accepted or explicitly deferred
