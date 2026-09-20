# Make validation_config.json Executable Policy

- **ID:** 0524
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0523

## Problem

`validation_config.json` declares `n_repeats: 20` and acceptance thresholds, and its hash is recorded in the acceptance artifact — but neither value is actually used to control the run. The validator hard-codes `5 if args.live else REPEATS` for repeat count, ignoring the config. `_check_thresholds()` retrieves thresholds into `t` but then uses hard-coded logic rather than the values in `t`. The config is versioned as if it is policy, but it is actually metadata. This breaks reproducibility: two runs at the same commit and config version can produce different acceptance decisions depending on which flags are passed at the command line.

## Proposed approach

- `n_repeats` in live mode: default to `config["n_repeats"]` rather than `5`. The `--n-repeats` flag remains as an explicit override (useful for smoke tests), but `--live` without `--n-repeats` must run the configured count.
- `_check_thresholds()`: every acceptance decision must be derived from `config["thresholds"][key]` rather than any hard-coded constant. Walk all required keys and fail at startup if any are missing from the loaded config.
- Add startup validation: enumerate the set of required threshold keys and assert all are present before running any tests. Log the resolved values at the start of the run so the acceptance artifact captures what was actually applied.
- Acceptance artifact: add a `resolved_config` field recording the effective values (n_repeats, each threshold) that controlled this run — distinct from `config_used` (the raw file) so future auditors can see both.
- Define two named run types in the config or via a flag: `smoke` (any N, cannot advance formal acceptance) and `acceptance` (must use configured N, can advance). The distinction must be explicit in the artifact.

## Touches

- `scripts/validate_macro_scorer.py` — n_repeats default, _check_thresholds(), startup validation, artifact fields
- `validation_config.json` — may need additional required threshold keys added

## Done when

- [ ] `--live` without `--n-repeats` uses `config["n_repeats"]` (currently 20), not the hard-coded 5
- [ ] Every decision in `_check_thresholds()` reads from `config["thresholds"]`, no hard-coded fallback
- [ ] Startup fails with a clear error if any required threshold key is absent from config
- [ ] Acceptance artifact includes `resolved_config` with effective n_repeats and all threshold values
- [ ] `smoke` vs `acceptance` run type is explicit in the artifact; smoke runs cannot advance `macro_acceptance_state`
