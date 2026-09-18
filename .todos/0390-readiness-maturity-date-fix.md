# Fix next_maturity_date to Use Earliest Unmatured Observation

- **ID:** 0390
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** none

## Problem

`learning_readiness_report()` computes `next_maturity_date` as `MAX(scored_at_date) + 91 days` over unmatured observations. The stated purpose is "earliest date when an unmatured observation can mature" — that requires `MIN`, not `MAX`. Using `MAX` reports the *last* date new evidence will arrive, not the *first*. A model with observations scored June 1 through July 1 will report maturity on October 1 when the first evidence actually arrives around September 1. The dashboard card misleads operators into waiting longer than necessary.

Additionally, for `sessions_v2` models the +91-day offset is approximate; the correct value is 63 NYSE sessions from `MIN(scored_at_date)`.

## Proposed approach

- Change `SELECT MAX(scored_at_date)` to `SELECT MIN(scored_at_date)` in `learning_readiness_report()`.
- For `sessions_v2` models, compute the 63rd future NYSE trading session after `MIN(scored_at_date)` rather than adding 91 calendar days. (Can reuse the market-session function added in 0389 if that ships first; otherwise a calendar-day approximation is acceptable as a stopgap.)
- Update the test `test_next_maturity_date_computed_from_unmatured_obs` to seed **multiple** observations at different dates and assert the result equals `MIN + horizon`, not `MAX + horizon`.

## Touches

- `agents/learning/calibration.py` — `learning_readiness_report()` lines ~1512-1521
- `tests/test_calibration.py` — `TestLearningReadinessReport0385::test_next_maturity_date_computed_from_unmatured_obs`

## Done when

- [ ] `next_maturity_date` = earliest unmatured `scored_at_date` + horizon (MIN, not MAX)
- [ ] Test seeds observations at ≥2 different dates and asserts MIN is used
- [ ] For `sessions_v2` models, offset uses 63 sessions or documents the approximation explicitly
- [ ] Full test suite passes
