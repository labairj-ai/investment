# Produce Immutable Macro Validation Acceptance Record

- **ID:** 0490
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0489

## Problem

1,219 passing unit tests prove the software behaves as specified, but they do not prove the Macro Risk data is reliable. The real gate before read-only Learning Lab integration is a durable validation record produced against the actual deployed model and frozen live inputs — not mocks. Thresholds must be defined before the run so they cannot be adjusted after seeing results.

## Proposed approach

Define thresholds in a `validation_config.json` before running:
- Schema-valid outputs: 100%
- Run-ledger integrity (expected == scored + failed): 100%
- Same-input score range across N=20 runs: ≤ 1 point per dimension
- Unexplained 2+ point swings: 0
- Anchor ordering failures: 0
- Synthetic beta recovery: within ±1.5
- Missing-data → UNKNOWN: 100%
- Unsupported fund → unsupported quality: 100%
- Provenance completeness (all 6 fields present): 100%

Run `scripts/validate_macro_scorer.py --live --n-repeats 20` against the deployed model with a frozen macro context snapshot. Write the output to `out/macro_validation_acceptance_YYYYMMDD.json` containing: commit SHA, model identity, prompt hash, schema hash, anchor results, N=20 repeatability stats, factor recovery, missingness tests, ledger integrity, and PASS/BLOCK verdict. This file is immutable — never overwritten, only added alongside.

Result is PASS if all thresholds met; BLOCK if any fail. BLOCK means Learning Lab integration does not proceed.

## Touches

- `scripts/validate_macro_scorer.py` — add `--live` and `--n-repeats` flags
- `out/macro_validation_acceptance_YYYYMMDD.json` — immutable output artifact
- `validation_config.json` — pre-defined thresholds

## Done when

- [ ] `validation_config.json` with thresholds exists and is committed before the run
- [ ] `--live` mode uses actual deployed model and real (or frozen) macro context snapshot
- [ ] Immutable acceptance record written to `out/` with commit SHA, model ID, all test results
- [ ] PASS/BLOCK verdict is machine-readable; exit 0 on PASS, exit 1 on BLOCK
- [ ] Record is never overwritten (timestamped filename or append-only)
