# Deterministic Degradation Window Query

- **ID:** 0407
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0401

## Problem

The degradation monitor now selects the latest N cohorts using:

```sql
SELECT DISTINCT decision_cohort_id
FROM model_observations
WHERE ...
ORDER BY id DESC
LIMIT ?
```

`DISTINCT` with an unaggregated `ORDER BY id DESC` does not deterministically define which row represents each cohort. Different query-planner decisions can produce different cohort orderings, making the degradation window non-reproducible for the same database state. Suspension/verdicts are high-stakes outputs; they should not depend on SQLite's internal DISTINCT implementation.

## Proposed approach

Replace with a deterministic grouped query:

```sql
SELECT decision_cohort_id, MAX(id) AS max_id
FROM model_observations
WHERE model_version = ?
  AND outcome_alpha_90d IS NOT NULL
  AND (observation_phase = 'PAPER_ACTIVE' OR observation_phase IS NULL)
  AND decision_cohort_id IS NOT NULL
GROUP BY decision_cohort_id
ORDER BY max_id DESC
LIMIT ?
```

Then fetch all rows belonging to those cohort IDs (existing pattern).

Add a test that inserts interleaved rows from multiple cohorts (cohort A, cohort B, cohort A again) and confirms the window selects the expected cohorts regardless of insertion order.

## Touches

- `agents/learning/calibration.py` — `_check_degradation()` cohort query
- Tests — add interleaved-cohort ordering test

## Done when

- [ ] Cohort window query uses `GROUP BY / MAX(id)` instead of `DISTINCT ... ORDER BY id`
- [ ] A test with interleaved rows confirms deterministic cohort selection
- [ ] Existing degradation tests still pass
