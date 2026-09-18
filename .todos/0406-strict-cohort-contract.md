# Strict Cohort Contract

- **ID:** 0406
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0398, 0399

## Problem

Two gaps remain after 0398/0399:

1. **Optional cohort_id**: `score_for_observe()` still accepts `cohort_id: str = None` and silently generates its own UUID if omitted. A new caller added later can accidentally reintroduce fragmented cohort identity without any error.

2. **No database-level invariant check**: 0399 enforces exactly one `would_select=1` and one `base_would_select=1` per cohort in Python, but there is no data-health query that detects violations already in the database. Corrupted historical cohorts would silently skew prospective metrics.

## Proposed approach

- Make `cohort_id` a required keyword-only argument:
  ```python
  def score_for_observe(model_version: str, candidates: list, *, cohort_id: str) -> None:
  ```
  Remove the UUID fallback. Fail loudly if not supplied.
- Consider persisting the Opportunity Hunter `run_id` alongside `decision_cohort_id` in `model_observations` for cross-table auditing.
- Add a data-health query in `compute_data_health()` (or a separate integrity check) that identifies "bad cohorts":
  ```sql
  SELECT decision_cohort_id
  FROM model_observations
  WHERE model_version = ?
  GROUP BY decision_cohort_id
  HAVING SUM(would_select) != 1 OR SUM(COALESCE(base_would_select, 0)) != 1
  ```
- Surface bad-cohort count in the health report; set overall health to BLOCK if any modern cohort (post-0399 deployment date) violates the invariant.

## Touches

- `agents/learning/challenger.py` — `score_for_observe()` signature
- `agents/opportunity_agent.py` — already passes cohort_id; verify no other caller exists
- `agents/learning/calibration.py` — `compute_data_health()` or new integrity function
- `agent_db.py` — possibly add `oh_run_id` column to `model_observations`
- Tests for mandatory cohort_id and invariant detection

## Done when

- [ ] `score_for_observe()` raises TypeError if `cohort_id` is not supplied
- [ ] Data-health check identifies cohorts with SUM(would_select) != 1 or SUM(base_would_select) != 1
- [ ] Health result is BLOCK when bad cohorts are found in modern observations
- [ ] A test inserts a malformed cohort and confirms the health check catches it
- [ ] OH run_id is persisted alongside decision_cohort_id (or explicitly deferred with justification)
