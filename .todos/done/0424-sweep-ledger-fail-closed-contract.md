# Sweep Ledger Fail-Closed Contract

- **ID:** 0424
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0418

## Problem

`score_for_observe()` wraps the `learning_sweep_runs` INSERT in a bare `except Exception: pass`,
so a ledger write failure silently continues into shadow scoring. This defeats the audit-trail
purpose: if the DB has a problem that affects only `learning_sweep_runs`, observations can be
written with no corresponding ledger record, making zero-row detection blind again.

Additionally, `agent_run_id` is never populated in the INSERT even though the column exists in
the schema and `score_for_observe()` receives a `cohort_id` from the caller that was derived
from the OH `agent_run_id`. Without it, the ledger row cannot be deterministically linked back
to the triggering OH invocation.

## Proposed approach

- Make `agent_run_id` a required parameter on `score_for_observe()` (or at minimum pass it
  through from the caller and persist it when present).
- In `opportunity_agent.py`, pass `ctx.run_id` (or equivalent run identifier) into
  `score_for_observe()` so it lands in `learning_sweep_runs.agent_run_id`.
- Change fail behavior on ledger INSERT: if the STARTED row cannot be created, abort shadow
  scoring and raise an exception back to the caller. Do NOT silently continue.
- Opportunity Hunter already wraps shadow scoring in a try/except that allows the base
  recommendation to continue, so the abort boundary is already in place — shadow failure must
  not affect the primary recommendation path.
- The invariant to enforce: learning observations must not exist without a corresponding
  STARTED ledger row.

## Touches

- `agents/learning/challenger.py` — `score_for_observe()` signature + ledger fail-closed logic
- `agents/opportunity_agent.py` — pass `agent_run_id` / `ctx.run_id` into `score_for_observe()`
- `tests/test_calibration.py` — test that ledger INSERT failure aborts scoring (not silently continues)

## Done when

- [ ] `agent_run_id` is persisted in `learning_sweep_runs` for every sweep
- [ ] Ledger INSERT failure causes shadow scoring to abort, not continue silently
- [ ] Base recommendation path is unaffected when shadow scoring aborts
- [ ] Test confirms abort-on-ledger-failure behavior
