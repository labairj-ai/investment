# Generate Stable Run-Scoped Decision Cohort ID

- **ID:** 0387
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0386

## Problem

`decision_cohort_id` is currently `datetime.now(timezone.utc).strftime("%Y%m%dT%H%M")` — UTC-minute granularity. Two Opportunity Hunter executions within the same minute collapse into one cohort, corrupting the comparison. Worse, if a single run crosses a minute boundary, the same underlying invocation gets split into two cohorts. Experimental identity must not be derived from a clock.

## Proposed approach

- Generate a UUID once at the start of each Opportunity Hunter invocation (or reuse the existing `agent_run_id` from `agent_runs` if the scorer is called from within a run).
- Pass that single ID into all `score_for_observe()` calls for that invocation as `decision_cohort_id`.
- The simplest path: add a `cohort_id` parameter to `score_for_observe()`; caller is responsible for generating once and passing through.
- Remove the UTC-minute fallback generation inside `score_for_observe()`.
- Open question: should `decision_cohort_id` be the `agent_runs.id` (integer) or a UUID string? Either works; prefer whatever the Opportunity Hunter already has available.

## Touches

- `agents/learning/challenger.py` — `score_for_observe()` signature and cohort ID generation
- Wherever `score_for_observe()` is called from the Opportunity Hunter pipeline
- `tests/test_calibration.py` — update `TestDecisionCohortEvaluation0382` / `TestDecisionCohortEvaluation0387`

## Done when

- [ ] `score_for_observe()` accepts an explicit `cohort_id` parameter (no default minute-clock generation)
- [ ] Each invocation of the Opportunity Hunter passes a single stable ID for all candidates scored in that run
- [ ] No two separate runs share a cohort ID; no single run produces multiple cohort IDs
- [ ] Tests verify the cohort ID is caller-supplied and stable across all rows in one call
- [ ] Full test suite passes
