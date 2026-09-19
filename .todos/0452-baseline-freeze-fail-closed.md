# Abort Baseline Freeze on Config or Policy Load Failure

- **ID:** 0452
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0450

## Problem

`freeze_baseline.py` catches failures in `_load_formula_params()`,
`_load_virtual_book_capital()`, `_load_policy_fields()`, and `_load_strategy_hash()`
and writes `{"import_error": "..."}` or `{"policy_error": "..."}` into the baseline
JSON rather than aborting. A baseline that cannot read the production formula is not
authoritative — it is a partial record that looks complete. Missing evidence is
categorically different from evidence saying "none," and a frozen baseline with an
`import_error` key silently violates the invariant the file is supposed to guarantee.

## Proposed approach

- Refactor each loader to raise an exception on failure instead of returning an error
  dict. In `main()`, catch these and call `sys.exit(1)` with a clear message naming
  which component failed and why.
- `--dry-run` mode may still display partial output for debugging, but should also
  print a clear "WOULD ABORT" notice rather than silently omitting the failure.
- Affected loaders: `_load_formula_params()`, `_load_virtual_book_capital()`,
  `_load_policy_fields()`, `_load_strategy_hash()`.
- `_load_db_fields()` failures (e.g. no active model) should also abort rather than
  producing a baseline with `model_version: null` — a null model is not a valid
  experiment starting point.

## Touches

- `scripts/freeze_baseline.py`

## Done when

- [ ] Any loader failure causes `freeze_baseline.py` to exit non-zero with a descriptive error
- [ ] No `import_error` or `policy_error` key can appear in a successfully written baseline
- [ ] `--dry-run` shows partial output but clearly labels failures
- [ ] A null or missing active model aborts the freeze
