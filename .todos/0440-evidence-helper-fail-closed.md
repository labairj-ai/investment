# Make Evidence Helpers Fail-Closed on DB Error

- **ID:** 0440
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0436

## Problem

`eligible_learning_cohorts()` and `_ineligible_ledger_cohorts()` both swallow all exceptions and
return empty `frozenset()`s. A database failure is therefore silent: callers that filter cohorts
through these helpers will behave as if there is simply no evidence, rather than knowing the
query failed. For promotion and degradation gates this is the wrong default — an empty result
should mean "no evidence exists," not "we couldn't check."

## Proposed approach

- Introduce `LearningEvidenceUnavailable` (new exception class in `calibration.py`).
- Remove the bare `except Exception: return frozenset()` in both helpers. Let real DB errors
  propagate as `LearningEvidenceUnavailable` (wrap the sqlite error).
- In `compute_prospective_metrics()`, `_check_degradation()`, and `learning_readiness_report()`:
  catch `LearningEvidenceUnavailable` and convert it to a BLOCK result with
  `reason = "ledger_query_failed"` rather than proceeding with an empty cohort set.
- Question: should `promote()` also catch this and reject the promotion, or is it sufficient to
  gate through `compute_prospective_metrics`?

## Touches

- `agents/learning/calibration.py`
- `tests/test_calibration.py`

## Done when

- [ ] `LearningEvidenceUnavailable` exception class exists in `calibration.py`
- [ ] `eligible_learning_cohorts()` raises `LearningEvidenceUnavailable` on DB error instead of returning `frozenset()`
- [ ] `_ineligible_ledger_cohorts()` raises `LearningEvidenceUnavailable` on DB error instead of returning `frozenset()`
- [ ] Promotion gate returns BLOCK (not pass) when evidence query fails
- [ ] Degradation check returns a safe/blocked result when evidence query fails
- [ ] Tests confirm DB-failure path produces BLOCK, not silent empty-cohort behavior
