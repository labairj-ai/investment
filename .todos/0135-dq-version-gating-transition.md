# Transition DQ CC-Management Exclusions to SQL Version Gating

- **ID:** 0135
- **Status:** backlog
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

CC management actions (HOLD_CALL, BUY_TO_CLOSE, ALLOW_ASSIGNMENT, ROLL_OUT, ROLL_UP, ROLL_UP_AND_OUT) are currently excluded from Decision Quality via a Python-side hardcode in `_EXCLUDE_FROM_DQ` (`agents/decision_quality.py`). The `outcome_math_version` column already exists (migration 0128) and is set to `2` for all CC management outcomes, but the SQL query in `get_outcome_statistics_by_category()` does not yet filter on it. The long-term design is to gate CC management rows by `outcome_math_version >= 2` in SQL and lift the Python exclusions — but this requires enough real v2 rows to have accumulated in the production database first.

## Proposed approach

- **Prerequisite check:** Query production DB: `SELECT outcome_math_version, COUNT(*) FROM recommendation_outcomes GROUP BY outcome_math_version`. Only proceed once v2 row count is large enough to produce meaningful statistics (define threshold — suggest ≥ 30 rows per action type at ≥ 3m horizon).
- Remove the six CC mgmt action names from `_EXCLUDE_FROM_DQ` in `agents/decision_quality.py`.
- Add `AND (outcome_math_version >= 2 OR action NOT IN (<cc_mgmt_list>))` (or equivalent) to the SQL in `agent_db.get_outcome_statistics_by_category()` so legacy v1 CC management rows (if any) are excluded while v2+ rows are included.
- Alternatively, add a separate `outcome_math_version` parameter to `get_outcome_statistics_by_category()` and let the caller specify the minimum version per action category.

Open question: should the minimum version threshold be stored as a constant next to `_EXCLUDE_FROM_DQ`, or embedded in the SQL query?

## Touches

- `agents/decision_quality.py` — remove CC mgmt actions from `_EXCLUDE_FROM_DQ`
- `agent_db.py` — `get_outcome_statistics_by_category()` SQL filter

## Done when

- [ ] CC management actions no longer appear in `_EXCLUDE_FROM_DQ`
- [ ] `get_outcome_statistics_by_category()` SQL filters out `outcome_math_version < 2` rows for CC management actions
- [ ] Decision Quality note renders a score for a HOLD_CALL/BUY_TO_CLOSE recommendation that has accumulated enough v2 outcomes
- [ ] `python -m pytest tests/` passes with no regressions
