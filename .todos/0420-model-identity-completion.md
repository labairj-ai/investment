# Model Identity Completion

- **ID:** 0420
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0416

## Problem

0416 added `model_id` (UUID), `training_config_hash`, and `code_commit_sha` as columns, but
`model_version TEXT PRIMARY KEY` remains the actual database identity. All observations,
promotion logs, lifecycle transitions, and loading still reference `model_version`. This creates
a concrete collision risk: if you retrain against the same data cutoff after changing
`ridge_alpha`, `MAX_ADJUSTMENT`, or `ALPHA_TO_SCORE_SCALE`, the `training_config_hash` changes
but `model_version` does not — the INSERT silently conflicts with the existing primary key.
The UUID is provenance metadata, not an identity.

## Proposed approach

Short-term (lower risk, backward-compatible):
- Include the first 8 chars of `training_config_hash` in `model_version`:
  `edge_<horizon>_<schema8>_<config8>_v<cutoff_seq>`
- Add a `UNIQUE` constraint on `model_id` in agent_db.py (migration: CREATE UNIQUE INDEX).
- This prevents silent collisions without a schema migration that touches foreign keys.

Long-term (preferred, but involves schema migration):
- Migrate `model_version` to a human-readable label (not PK).
- Make `model_id UUID` the PRIMARY KEY.
- Update `model_observations`, `decision_variants`, `promotion_log` (and any other tables)
  to reference `model_id` rather than `model_version`.
- Keep `model_version` as a display/log field.

Open question: is a breaking schema migration acceptable right now, or should we do the
short-term config-hash-in-version fix first and defer the UUID-PK migration?

## Touches

- `agent_db.py` — UNIQUE INDEX on model_id; optionally schema migration for UUID PK
- `agents/learning/calibration.py` — `_generate_model_version()` to include config hash suffix
- `agents/learning/challenger.py` — no change if model_version format change is backward compatible
- `tests/test_calibration.py` — update version format regex; test collision prevention

## Done when

- [ ] Retraining against the same cutoff with a different config does not silently overwrite
      the existing model row (either via a new version string or a UNIQUE model_id constraint)
- [ ] `model_id` has a UNIQUE constraint in the database schema
- [ ] `model_version` format includes config hash component OR a UUID-PK migration is applied
