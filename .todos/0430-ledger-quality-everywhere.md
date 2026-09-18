# Centralize Eligible-Cohort Predicate Across All Learning Paths

- **ID:** 0430
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0429

## Problem

The definition of an "eligible learning cohort" (COMPLETED sweep with scored_candidates == expected_candidates) is duplicated ad-hoc across promotion and readiness, and is entirely absent from `_check_degradation()` and SUSPENDED recovery. A PARTIAL or FAILED sweep can therefore influence ranking spread, selection delta, degradation hysteresis, and automatic suspension decisions — exactly the audit surface 0429 was supposed to close.

## Proposed approach

- Extract a single helper `eligible_learning_cohorts(conn, model_version, phase=None) -> set[str]` returning cohort_ids where `status='COMPLETED' AND scored_candidates=expected_candidates`.
- Replace the ad-hoc `filter_partial_ledger=True` logic in `compute_prospective_metrics()` and `_check_promotion_gates()` with calls to this helper.
- Apply the same helper inside `_check_degradation()` to filter the mature-outcome window before computing ranking spread, selection delta, and the hysteresis counter.
- Apply it to the SUSPENDED → OBSERVE recovery evidence query.
- Question: should pre-0424 rows (no ledger at all) continue to be allowed through as legacy, or blocked? Current plan: allow through as legacy in all paths (consistent with 0429 decision) until 0432 phases them out.

## Touches

- `agents/learning/calibration.py` — `_check_degradation()`, `_check_promotion_gates()`, `compute_prospective_metrics()`, `learning_readiness_report()`
- `tests/test_calibration.py` — tests for degradation with PARTIAL sweep data

## Done when

- [ ] `eligible_learning_cohorts()` (or equivalent private helper) is the single definition used by promotion, readiness, degradation, and recovery
- [ ] `_check_degradation()` excludes PARTIAL/FAILED cohorts from its mature-outcome window
- [ ] A test confirms that a PARTIAL PAPER_ACTIVE sweep does not influence the degradation verdict
- [ ] No duplicated eligibility SQL remains across the four call sites
