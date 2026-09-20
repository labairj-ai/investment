# Require Non-Overlapping Cohorts for Degradation Suspension

- **ID:** 0377
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0374

## Problem

`_check_degradation()` (0371) computes a 30-observation rolling window and
auto-suspends a model on 2 consecutive NEGATIVE verdicts. But consecutive 30-obs
windows overlap by ~29 rows: each new snapshot adds one outcome-matured observation
and drops the oldest. Two consecutive NEGATIVE verdicts are therefore almost entirely
correlated — they confirm the same 29 candidates' poor outcomes, not two independent
samples. The "consecutive" signal provides almost no additional confidence over a
single window.

Additionally, the current state machine only has `OBSERVE → PAPER_ACTIVE → SUSPENDED`,
so there is no soft warning before suspension. A single bad batch of outcomes can
produce two overlapping NEGATIVE windows in rapid succession and trigger a hard
suspension with no intermediate signal.

## Proposed approach

**Option A — Non-overlapping cohorts (preferred)**

Track `last_degradation_snapshot_max_episode_id` (or observation timestamp) in
`model_performance_snapshots`. The next snapshot only runs when at least N new
outcomes have matured since the previous snapshot (default N=15, configurable). This
means "2 consecutive NEGATIVE" verdicts require at least 15 genuinely new observations
between them, reducing correlation from ~97% to ~50%.

**Option B — WARNING state (additional safety)**

Add `LIFECYCLE_DEGRADED = "DEGRADED"` between `PAPER_ACTIVE` and `SUSPENDED`.
A PAPER_ACTIVE model with 1 NEGATIVE non-overlapping verdict → DEGRADED. A DEGRADED
model with a second NEGATIVE non-overlapping verdict → SUSPENDED. A DEGRADED model
with a POSITIVE verdict → back to PAPER_ACTIVE. Adds one extra state transition.

Both options can be combined: non-overlapping cohorts + WARNING/DEGRADED state.

## Touches

- `agent_db.py` — `_new_cols`: `last_snapshot_max_obs_id INTEGER` on
  `model_performance_snapshots` (for non-overlapping anchor)
- `agents/learning/calibration.py` — `_check_degradation()`: enforce non-overlapping
  cohorts before evaluating verdict; optional: add LIFECYCLE_DEGRADED constant and
  transitions; update auto-suspend logic to require 2 non-overlapping NEGATIVE verdicts
- `tests/test_calibration.py` — test that two verdicts with < 15 new observations
  between them do NOT trigger suspension; test that 2 non-overlapping NEGATIVE verdicts
  DO trigger suspension

## Done when

- [ ] `_check_degradation()` only evaluates a new window when ≥ N new outcomes have
  matured since the previous snapshot
- [ ] "2 consecutive NEGATIVE" means 2 non-overlapping cohorts, not 2 rolling windows
- [ ] (Optional) LIFECYCLE_DEGRADED state added with correct transitions
- [ ] Test: rapid outcome maturation with bad outcomes doesn't trigger instant suspension
  from overlapping windows
- [ ] `python -m pytest tests/` passes with no regressions
