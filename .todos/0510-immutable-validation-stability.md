# Immutable Validation Stability — Tie to Acceptance Record

- **ID:** 0510
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0506

## Problem

`macro_dimension_stability` has no `acceptance_record_id` column, so validated stability is not tied to the specific acceptance run that established it. Worse, two writers share the same mutable table: the validation script writes stability for every live run (including runs that later produce BLOCK), and the routine scorer overwrites the same rows with its own adaptive-sampling stddev. A later failed validation or a weekly scoring run with more variable samples can silently overwrite a formally validated STABLE classification.

## Proposed approach

Add provenance columns to `macro_dimension_stability`:
- `acceptance_record_id TEXT` — filename of the PASS acceptance record that wrote this row
- `config_version TEXT` — validation_config version (e.g. "v1.1")
- `config_hash TEXT` — SHA-256 of validation_config.json at run time
- `model_identity TEXT` — exact model used
- `validation_run_type TEXT` — "accepted_validation" | "failed_validation" | "runtime_sampling"
- `recorded_at TEXT`

Change the PRIMARY KEY to `(ticker, dimension, acceptance_record_id)` so multiple validation runs produce distinct rows rather than overwriting.

Routing rules:
- Validation script writing after a PASS run: `validation_run_type = "accepted_validation"`, with acceptance_record_id populated
- Validation script writing after a BLOCK run: `validation_run_type = "failed_validation"` — stored for diagnostics, never promoted to usable
- Routine scorer: `validation_run_type = "runtime_sampling"` — never overwrites accepted rows

The "canonical" stability for a ticker×dim is the most recent `accepted_validation` row. Runtime rows are stored separately and used for adaptive N decisions only.

## Touches

- `portfolio_ai.py` — `macro_dimension_stability` schema, writes from scorer
- `scripts/validate_macro_scorer.py` — writes stability only after confirmed PASS; tags acceptance_record_id

## Done when

- [ ] `macro_dimension_stability` has `acceptance_record_id`, `config_version`, `config_hash`, `model_identity`, `validation_run_type`
- [ ] BLOCK validation runs write with `validation_run_type = "failed_validation"` and cannot promote any dimension to usable
- [ ] Routine scorer writes with `validation_run_type = "runtime_sampling"` and cannot overwrite `accepted_validation` rows
- [ ] Canonical stability = most recent `accepted_validation` row per ticker×dim
