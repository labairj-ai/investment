# Replace Fixed 91-Day CV Embargo with Horizon-Exact maturity_date()

- **ID:** 0414
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0405

## Problem

`_cv_walk_forward()` still uses a hard-coded 91-calendar-day embargo (`EMBARGO_DAYS = 91`) to separate training folds from validation. The canonical learning target is now `sessions_v2` / 3m = 63 NYSE trading sessions, which can mature later than 91 calendar days depending on holiday placement. This creates potential target-window overlap between training and validation folds, reintroducing the approximation that `maturity_date()` was added to eliminate everywhere else.

## Proposed approach

- Add a `horizon_version` parameter to `_cv_walk_forward()` (default `"calendar_v1"` for backward compat).
- Replace the `embargo_end = cutoff + timedelta(days=EMBARGO_DAYS)` line with:
  `embargo_end = date.fromisoformat(maturity_date(cutoff.isoformat(), horizon_version, "3m"))`
- Pass the model's `training_horizon_version` through from `ChallengerModel.train()`.
- Update comments to reflect the session-count embargo.
- Verify that for `sessions_v2` the embargo date is always >= the old 91-day date (it will be in weeks with many holidays).

## Touches

- `agents/learning/calibration.py` — `_cv_walk_forward()`, `ChallengerModel.train()`
- `tests/test_calibration.py` — assert sessions_v2 embargo falls on a trading day and is >= 91 calendar days from cutoff

## Done when

- [ ] `_cv_walk_forward()` accepts `horizon_version` and derives embargo from `maturity_date()`
- [ ] `ChallengerModel.train()` passes its `horizon_version` through to `_cv_walk_forward()`
- [ ] For `sessions_v2`, the embargo end is a NYSE trading day and never shorter than 91 calendar days
- [ ] Existing CV tests still pass
