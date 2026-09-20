# Require COMPLETED Ledger for Post-Rollout Model Promotion

- **ID:** 0432
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0430

## Problem

Pre-0424 observations have no ledger row and are allowed through promotion/degradation gates as "legacy." This is fine for historical models, but a future PAPER_ACTIVE model trained after the ledger-contract rollout (commit 12ed25f) could still qualify for promotion partly on evidence that cannot satisfy the provenance standard now built into the pipeline. The legacy exemption should be time-bounded: only observations for models created before the rollout cutoff should be treated as legacy-unverified.

## Proposed approach

- Record the rollout cutoff (model `created_at` timestamp corresponding to commit 12ed25f) as a constant in `calibration.py`.
- Classify each observation cohort as one of: `VERIFIED_MODERN` (has COMPLETED ledger), `LEGACY_UNVERIFIED` (no ledger, model created before cutoff), `INCOMPLETE` (PARTIAL/FAILED ledger).
- For models created after the cutoff: promotion and degradation gates must use only `VERIFIED_MODERN` cohorts; `LEGACY_UNVERIFIED` is excluded.
- For models created before the cutoff: current behavior preserved (legacy rows allowed through).
- `learning_readiness_report()` should surface cohort provenance breakdown.
- Open question: what is the exact cutoff timestamp to encode? Use the `created_at` of the first model trained after 12ed25f merged.

## Touches

- `agents/learning/calibration.py` — `eligible_learning_cohorts()` (from 0430), `learning_readiness_report()`
- `tests/test_calibration.py` — tests for post-cutoff model with unledgered cohorts excluded

## Done when

- [ ] Rollout cutoff constant defined in `calibration.py`
- [ ] Post-cutoff models exclude `LEGACY_UNVERIFIED` cohorts from promotion and degradation
- [ ] Pre-cutoff models retain current legacy-allowed behavior
- [ ] `learning_readiness_report()` includes provenance breakdown (verified/legacy/incomplete counts)
- [ ] Tests confirm a post-cutoff model with unledgered cohorts cannot promote on legacy evidence alone
