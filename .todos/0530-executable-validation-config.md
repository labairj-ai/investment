# Make All Validation Thresholds Executable Config

- **ID:** 0530
- **Status:** backlog
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0529

## Problem

`validate_macro_scorer.py` declares several thresholds in `validation_config.json` (e.g. `same_input_score_max_range`, `beta_recovery_tolerance`, `provenance_completeness_pct`) but does not actually apply them in verdict calculations — `_check_thresholds()` largely asks whether a module returned "PASS" rather than comparing against the configured numeric value. Hard-coded constants (`STDEV_WARN_THRESHOLD = 1.0`, synthetic regression tolerances `1.5, 1.5, 0.5`) remain in code and override whatever the config says. Malformed `validation_config.json` is silently replaced with defaults, meaning a corrupted acceptance contract does not prevent acceptance from proceeding.

## Proposed approach

- Delete `STDEV_WARN_THRESHOLD`, `DRIFT_THRESHOLD`, and the three hard-coded synthetic regression tolerances; load all values from config.
- `_check_thresholds()` must compare each module's numeric output against its configured threshold directly, not defer to an upstream "PASS" string.
- Implement `same_input_score_max_range` explicitly in repeatability checks (currently unused).
- Either implement `provenance_completeness_pct` and `schema_valid_pct` with real measurement, or remove them from `_REQUIRED_THRESHOLDS` until they exist.
- On load: raise a hard error (not a warning + default) for malformed JSON, unknown threshold names, or missing required threshold names.
- Add parameterized tests: for every threshold in `_REQUIRED_THRESHOLDS`, a test tweaks that threshold across its boundary and asserts the verdict flips.

Open question: should threshold validation happen at config load time (fail-fast) or inside `_check_thresholds()` (lazy)? Fail-fast at load is safer for an acceptance system.

## Touches

- `validate_macro_scorer.py` (threshold loading, `_check_thresholds`, repeatability, synthetic regression)
- `validation_config.json` (may need schema annotation or a JSON Schema file)
- Test suite (new threshold-boundary tests)

## Done when

- [ ] No numeric threshold constant remains hard-coded in validation logic; all are loaded from config
- [ ] `same_input_score_max_range` is applied in the repeatability verdict
- [ ] Malformed or unknown config keys raise a fatal error rather than falling back to defaults
- [ ] `provenance_completeness_pct` and `schema_valid_pct` are either implemented or removed from the required-threshold list
- [ ] Parameterized test confirms every threshold independently gates the verdict when its boundary is crossed
