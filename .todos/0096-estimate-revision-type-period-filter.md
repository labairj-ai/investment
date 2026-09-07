# Filter Estimate Revision Dependencies by Type and Period

- **ID:** 0096
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** none

## Problem

`_check_estimate_revision()` in `dependency_checker.py` queries `estimate_history` for the most recent row for a ticker regardless of estimate type or period. A recommendation that was created based on an FY2027 EPS estimate of $12.20 can be compared against the latest row in `estimate_history` which might be next-quarter revenue — completely different metrics. This can either suppress a real invalidation (estimate type changed, revision wasn't caught) or trigger a false invalidation (different estimate type moved but the original didn't).

## Proposed approach

- Dependencies of type `ESTIMATE_REVISION` should carry `estimate_type` (e.g., `"EPS"`) and `period` (e.g., `"FY2027"`) in their metadata (stored in `dependency_key` or a JSON `original_value` envelope)
- Update the query in `_check_estimate_revision()` to filter by `estimate_type` and `period`:
  ```sql
  SELECT estimate_value FROM estimate_history
  WHERE ticker=? AND estimate_type=? AND period=?
  ORDER BY captured_at DESC LIMIT 1
  ```
- Update whichever agent(s) emit ESTIMATE_REVISION dependencies to include `estimate_type` and `period` in the stored metadata
- If `estimate_type`/`period` are absent (legacy rows), fall back to current behavior with a logged warning

## Touches

- `agents/dependency_checker.py`
- `agent_db.py` (schema of `estimate_history` table — verify `estimate_type` and `period` columns exist)
- Whichever agent(s) create ESTIMATE_REVISION dependencies (likely `sell_trim_agent.py` or `thesis_agent.py`)

## Done when

- [ ] `_check_estimate_revision()` filters by `estimate_type` and `period` when those fields are present in the dependency metadata
- [ ] Agents that emit ESTIMATE_REVISION dependencies store `estimate_type` and `period` in the dependency record
- [ ] Unit test: FY2027 EPS dependency is NOT invalidated when a Q3 revenue estimate changes
- [ ] Unit test: FY2027 EPS dependency IS invalidated when the FY2027 EPS estimate moves beyond threshold
- [ ] Unit test: legacy row without `estimate_type` falls back gracefully (no crash, logs a warning)
- [ ] Regression: existing dependency checker tests still pass
