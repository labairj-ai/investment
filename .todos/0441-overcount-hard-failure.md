# Raise Immediately on Observation Over-Count

- **ID:** 0441
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0431

## Problem

When `score_for_observe()` detects `actual_count > expected_count` it marks the ledger row as
FAILED but then returns normally. The caller sees a completed call with no indication anything went
wrong. An over-count is structurally impossible under correct operation — it signals cohort reuse,
duplicate observations, broken uniqueness, or wrong candidate expectations. Silently continuing
means the failure surfaces only through the canary's next run rather than at the point of violation.

## Proposed approach

- After writing `status='FAILED'` for the over-count case, immediately raise
  `LearningIntegrityError` (or a new `LearningOvercountError` subclass).
- The raise must happen *after* the ledger is updated so the FAILED row is persisted before the
  exception unwinds the call stack.
- Callers of `score_for_observe()` (the OH scheduler / runner) will receive the exception and
  can halt the cycle rather than proceeding with a corrupt cohort.
- Question: should this share `LearningIntegrityError` with 0440's `LearningEvidenceUnavailable`,
  or be a distinct exception? A common base class (e.g. `LearningPipelineError`) would let callers
  catch either with one handler.

## Touches

- `agents/learning/challenger.py`
- `tests/test_calibration.py`

## Done when

- [ ] `score_for_observe()` raises after marking FAILED when `actual_count > expected_count`
- [ ] The FAILED ledger row is persisted before the exception is raised
- [ ] Caller receives the exception (it is not swallowed inside `score_for_observe`)
- [ ] Test confirms over-count raises and the DB row is FAILED
- [ ] Under-count (partial) path is unaffected — still marks PARTIAL and returns normally
