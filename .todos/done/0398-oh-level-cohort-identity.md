# Generate and Propagate Cohort ID at Opportunity Hunter Level

- **ID:** 0398
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** none

## Problem

`score_for_observe()` accepts a `cohort_id` parameter, but `run_opportunity_hunter()` never generates or passes one. Each individual scorer call therefore creates its own UUID, so observations from the same OH sweep that are processed by different model states (OBSERVE, PAPER_ACTIVE, SUSPENDED) receive different cohort IDs. This makes it impossible to unambiguously identify which predictions came from the exact same candidate sweep, which is a prerequisite for meaningful cross-model comparison and experiment accounting.

## Proposed approach

- At the top of `run_opportunity_hunter()`, generate one run-scoped UUID (or reuse `ctx.run_id` if that concept exists in the execution context).
- Pass that ID as `cohort_id=` to every `score_for_observe()` call made within the sweep.
- After all legacy callers are updated, make `cohort_id` a required parameter in `score_for_observe()` to prevent future callers from silently omitting it.
- Open question: does a `ctx.run_id` already exist in the OH execution context, or does a new one need to be created/persisted?

## Touches

- `run_opportunity_hunter()` (or equivalent OH entry point)
- `score_for_observe()` signature and call sites
- Any tests that call `score_for_observe()` without a `cohort_id`

## Done when

- [ ] A single cohort ID is generated once per `run_opportunity_hunter()` invocation
- [ ] That ID is passed to every `score_for_observe()` call within the sweep
- [ ] All three model states (OBSERVE, PAPER_ACTIVE, SUSPENDED) write the same cohort ID for the same sweep
- [ ] `cohort_id` is a required parameter (no default UUID generation inside the scorer)
- [ ] Existing tests updated; new test asserts all observations from one OH run share one cohort ID
