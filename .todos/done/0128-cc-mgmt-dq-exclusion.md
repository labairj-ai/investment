# Exclude CC Management Actions from Decision Quality + Add outcome_math_version

- **ID:** 0128
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** none

## Problem

CC management actions (HOLD_CALL, BUY_TO_CLOSE, ALLOW_ASSIGNMENT, ROLL_OUT, ROLL_UP, ROLL_UP_AND_OUT) use the wrong outcome math (wrong denominator, wrong HOLD_CALL model, wrong ALLOW_ASSIGNMENT branching — see 0125–0127). These rows are currently eligible for Decision Quality scoring, which contaminates the alpha and win-rate metrics for the portfolio with economically incorrect return figures.

Longer-term, once the math is fixed, we need a way to distinguish "old-formula outcomes" from "new-formula outcomes" so we can backfill or filter correctly.

## Proposed approach

**Short-term (this todo):**
- Add `HOLD_CALL`, `BUY_TO_CLOSE`, `ALLOW_ASSIGNMENT`, `ROLL_OUT`, `ROLL_UP`, `ROLL_UP_AND_OUT` to `_EXCLUDE_FROM_DQ` in `agents/decision_quality.py`. This immediately stops contaminated rows from appearing in DQ stats.

**Longer-term (same PR or follow-up):**
- Add `outcome_math_version INTEGER` column to `recommendation_outcomes` via an `ALTER TABLE` migration in `agent_db.migrate()`. Default NULL for legacy rows.
- Set `outcome_math_version = 1` on all new outcome rows written by the current evaluator (pre-NAV fix).
- When 0125–0127 are implemented, bump to `outcome_math_version = 2` and update the DQ query to require `outcome_math_version >= 2` for CC management actions, or remove them from `_EXCLUDE_FROM_DQ`.
- Add a migration test that verifies older DBs without the column are handled gracefully (column added with NULL default).

## Touches

- `agents/decision_quality.py` — `_EXCLUDE_FROM_DQ` set
- `agent_db.py` — `migrate()`, new column
- `agents/outcome_evaluator.py` — set `outcome_math_version` on all writes
- `tests/test_lifecycle.py` or new test file — migration and DQ exclusion tests

## Done when

- [ ] `_EXCLUDE_FROM_DQ` includes all six CC management action types
- [ ] No CC management outcomes appear in Decision Quality alpha/win-rate queries
- [ ] `recommendation_outcomes` has `outcome_math_version INTEGER` column (NULL-safe migration)
- [ ] Evaluator sets `outcome_math_version = 1` on every new row
- [ ] Test verifies a HOLD_CALL outcome is excluded from DQ results
- [ ] Test verifies `outcome_math_version` column is present after `migrate()` on a fresh DB
