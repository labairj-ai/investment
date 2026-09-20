# Replace Timestamp Rollout Boundary with Evidence Contract Version

- **ID:** 0438
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0432

## Problem

`LEDGER_ROLLOUT_CUTOFF = 1789769915.0` determines whether a model uses strict (modern) or legacy ledger semantics based on its `created_at` wall-clock timestamp. A timestamp is a fragile proxy for "this model was trained under evidence-contract version 2" — it breaks on DB restores, clock anomalies, manual imports, and future migrations. The actual semantic is about the contract under which the model's evidence was collected, not when the clock said it was trained.

## Proposed approach

- Add `evidence_contract_version` column to `learning_models` (e.g., integer; NULL = legacy/0, 1 = ledger_v1).
- Set `evidence_contract_version=1` on all new models going forward (in `ChallengerModel.save_with_weights()` or `train_and_save()`).
- In `compute_prospective_metrics()` and `_check_degradation()`: replace the `_mv_created_at > LEDGER_ROLLOUT_CUTOFF` check with `evidence_contract_version >= 1`.
- Keep `LEDGER_ROLLOUT_CUTOFF` as migration-only fallback for old rows that lack the column (read `evidence_contract_version`; if NULL, fall back to timestamp comparison).
- In `learning_readiness_report()`: surface `evidence_contract_version` in `provenance_breakdown`.
- Eventually (once all live models carry the field): remove `LEDGER_ROLLOUT_CUTOFF` fallback entirely.

## Touches

- `agent_db.py` — schema migration to add `evidence_contract_version` column
- `agents/learning/calibration.py` — `ChallengerModel.save_with_weights()` / `train_and_save()`, `compute_prospective_metrics()`, `_check_degradation()`, `learning_readiness_report()`
- `tests/test_calibration.py` — test that new models get evidence_contract_version=1; test that legacy models still use timestamp fallback

## Done when

- [ ] `evidence_contract_version` column exists in `learning_models`
- [ ] New models written with `evidence_contract_version=1`
- [ ] Gate logic reads the column; falls back to timestamp only when NULL
- [ ] `provenance_breakdown` in readiness report includes `evidence_contract_version`
- [ ] `LEDGER_ROLLOUT_CUTOFF` is documented as migration-only, not permanent policy
