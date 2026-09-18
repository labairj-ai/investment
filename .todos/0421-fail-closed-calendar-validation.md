# Fail-Closed Calendar Validation

- **ID:** 0421
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0414

## Problem

`_cv_walk_forward()` introduced a try/except fallback (0414) that silently returns to a 91-day
calendar approximation if `maturity_date()` raises an exception. For model validation, that
fallback is more dangerous than the error itself: a calendar library failure quietly relaxes the
embargo and potentially allows return-window leakage between training and validation data. A
failed maturity calculation should never have the side effect of weakening embargo enforcement.

## Proposed approach

- Remove the `except` branch that falls back to `cutoff + 91 days` in `_cv_walk_forward()`.
- Replace with fail-closed behavior: on any exception from `maturity_date()`:
  - Log the error at ERROR level.
  - SKIP the affected fold (continue to the next fold) rather than evaluate with a relaxed embargo.
  - If ALL folds are skipped (calendar fully broken), ABORT training and return None from
    `ChallengerModel.train()`.
- The 91-day fallback can remain in non-CV paths (e.g., display/reporting) where it's not a
  correctness risk, but never in the CV embargo calculation.
- Add a test that mocks `maturity_date()` to raise and asserts the fold is skipped (not that
  training proceeds with a 91-day embargo).

## Touches

- `agents/learning/calibration.py` — `_cv_walk_forward()` exception handling
- `tests/test_calibration.py` — test that mocks maturity_date failure and checks fold is skipped

## Done when

- [ ] `_cv_walk_forward()` has no fallback to 91-day calendar approximation on calendar error
- [ ] A `maturity_date()` exception causes the affected fold to be skipped, not evaluated
  with a weaker embargo
- [ ] If all folds are skipped, `ChallengerModel.train()` returns None
- [ ] Test confirms fold is skipped (not that training silently proceeds) when calendar fails
