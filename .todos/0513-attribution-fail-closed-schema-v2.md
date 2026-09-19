# Attribution Fail-Closed + Macro Score Schema V2

- **ID:** 0513
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0512

## Problem

Two issues. First, `macro_attribution.py` has a `get(key, True)` default — missing usability metadata is treated as usable for backward compatibility. A legacy score produced before usability fields existed passes through the ACCEPTED filter and enters formal attribution without any per-dimension quality gate. Second, `MACRO_SCORE_SCHEMA_VERSION` is still `"v1"` despite the score object gaining distributions, stability classes, per-dim usability, interaction version, and expanded provenance — exactly when schema versioning matters.

## Proposed approach

**Schema v2**: bump `MACRO_SCORE_SCHEMA_VERSION = "v2"`. V2 score objects must carry:
- `rate_sensitivity_usable_for_attribution`, `dollar_sensitivity_usable_for_attribution`, etc.
- `validated_stability` per dim (from 0511)
- `rate_sensitivity_median`, `rate_sensitivity_stddev`, etc. (from 0507)
- `macro_interaction_version = "macro_interaction_v1"`

**Attribution fail-closed**: change the usability check from:
```python
e["macro"].get(f"{dim}_usable_for_attribution", True) is not False  # WRONG
```
to:
```python
e["macro"].get(f"{dim}_usable_for_attribution") is True  # explicit True only
```

**Schema version gate**: formal attribution requires `schema_version == "v2"`:
```python
schema_ok = e["macro"].get("schema_version") == "v2"
if not schema_ok:
    legacy_count += 1
    continue  # skip — legacy score, not eligible for formal attribution
```

**Validator output record**: change the hard-coded `"version": "v1"` in the acceptance record output to use `config_version` from `validation_config.json`, plus add `acceptance_contract` and `validation_config_hash` fields separately.

Add `--include-legacy` flag to `macro_attribution.py` for diagnostic viewing of pre-v2 episodes.

## Touches

- `portfolio_ai.py` — `MACRO_SCORE_SCHEMA_VERSION = "v2"`
- `scripts/macro_attribution.py` — fail-closed usability check, schema version gate, `--include-legacy` flag
- `scripts/validate_macro_scorer.py` — acceptance record distinguishes `acceptance_contract` from `validation_config_version`

## Done when

- [ ] `MACRO_SCORE_SCHEMA_VERSION = "v2"`
- [ ] New scores carry all v2 fields (per-dim usability, distributions, validated_stability)
- [ ] Attribution: `get(key, True)` removed; explicit `is True` check used
- [ ] Attribution: skips episodes with schema_version != "v2" by default; `--include-legacy` for diagnostics
- [ ] Acceptance record output distinguishes `acceptance_contract` from `validation_config_version` + hash
