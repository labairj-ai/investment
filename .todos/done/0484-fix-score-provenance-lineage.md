# Fix Score Provenance Lineage and Full Hashes

- **ID:** 0484
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0475, 0480

## Problem

`evidence_hash` is computed and stored in `holding_macro_scores_history` but never attached to the score object itself, so `scores.get("evidence_hash")` in the drift classifier always returns None. The model-version comparison in `generate_macro_score_summary` reads `scores.get("schema_version")` and compares it against the previous model version — comparing schema version to model identity. Provenance hashes are also truncated to 16 hex chars with no benefit; full SHA-256 should be stored.

## Proposed approach

- Attach `evidence_hash`, `run_id`, `model_version`, `schema_version`, `prompt_hash`, and `scored_at` to the score dict before inserting into results, so downstream consumers (drift classifier, summary) can read them directly.
- Fix the `generate_macro_score_summary` version comparison: use `scores.get("model_version")` vs `prev.get("model_version")` and `scores.get("schema_version")` vs `prev.get("schema_version")` separately.
- Store full SHA-256 (64 chars) for `evidence_hash` and `macro_hash` — drop truncation.
- Add a `prompt_version` field (e.g. semantic version string) incremented manually when the prompt template changes, distinct from `schema_version`.

## Touches

- `portfolio_ai.py` — `generate_holding_macro_scores()`, `generate_macro_score_summary()`

## Done when

- [ ] Score dict contains `evidence_hash`, `model_version`, `schema_version`, `run_id`, `scored_at`
- [ ] Drift classifier can classify `evidence_driven` vs `version_artefact` without hitting None
- [ ] Model-version and schema-version comparisons use the correct respective fields
- [ ] Stored hashes are full 64-char SHA-256
