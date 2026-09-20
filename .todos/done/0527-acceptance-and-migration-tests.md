# Harden Migration and Add Acceptance Test Suite

- **ID:** 0527
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0523, 0524, 0525, 0526

## Problem

The 5055d6b commit changes three production files but adds no tests. The table-split migration in `_init_ai_tables()` is guarded only by checking whether `macro_dimension_validation` is empty — if anything goes wrong during migration the exception is swallowed. The acceptance activation path, config-controlled thresholds, usability gate, and geo quality contract all have correctness properties that must be verified to catch regressions as the system evolves toward autonomous execution.

## Proposed approach

Add the following tests to `tests/` (likely a new `test_macro_acceptance.py`):

- `test_acceptance_activation_rolls_back_on_db_lock` — simulate a DB write failure during activation; assert old `macro_acceptance_state` is unchanged and exit code is non-zero
- `test_config_controls_live_repeat_count` — assert that `--live` without `--n-repeats` uses `config["n_repeats"]`, not the hard-coded 5
- `test_config_thresholds_control_verdict` — set a threshold to something that should change the verdict; assert the verdict changes accordingly
- `test_usability_requires_active_record` — assert `_is_formally_usable()` returns False when `macro_acceptance_state` has no row, even if `macro_dimension_validation` has matching rows
- `test_validated_stability_uses_active_record` — assert that `*_validated_stability` fields in a score blob are sourced from `macro_dimension_validation` with the current active `record_id`, not from `macro_dimension_stability`
- `test_geo_missing_source_date_not_full` — assert `_geo_evidence_quality()` returns `"partial"` (not `"full"`) for a `confidence="high"` row with no `source_date`
- `test_macro_migration_is_idempotent` — run `_init_ai_tables()` twice on the same DB; assert row counts and content are identical after the second call

Also harden the migration itself:
- Version the migration with a `_schema_migrations` table or a version key so it can be made truly idempotent (not just "skip if empty")
- Wrap the row-copy loop in a savepoint so a mid-migration failure doesn't leave the new tables partially populated

## Touches

- `tests/test_macro_acceptance.py` — new test file (7 tests above)
- `portfolio_ai.py` — `_init_ai_tables()` migration hardening (versioned, savepoint-guarded)

## Done when

- [ ] All 7 named tests exist and pass
- [ ] `_init_ai_tables()` migration is idempotent when run on a DB that has already been migrated
- [ ] Migration row-copy is wrapped in a savepoint; failure leaves new tables empty (not partial)
- [ ] No existing tests broken by the hardening changes
