# Learning Sweep Ledger and Zero-Row Detection

- **ID:** 0418
- **Status:** backlog
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0412

## Problem

The candidate-coverage integrity check (0413) cannot detect zero-row cohorts because it starts
from model_observations via an inner join — if shadow scoring produced zero rows, the cohort
simply doesn't appear and the check passes silently. A sweep that was expected to score 24
candidates but scored 0 is completely invisible to the audit. Additionally, the coverage check
only validates PAPER_ACTIVE cohorts; OBSERVE cohorts (the evidence used to promote a model)
and SUSPENDED cohorts are not validated at all.

## Proposed approach

- Add a `learning_sweep_runs` table (migration in agent_db.py):
  `cohort_id TEXT, model_version TEXT, agent_run_id TEXT, phase TEXT,
   expected_candidates INT, scored_candidates INT, started_at TEXT,
   completed_at TEXT, status TEXT, error TEXT`
- In `score_for_observe()`, INSERT the row with `status='STARTED'` and `expected_candidates=len(candidates)`
  before the scoring loop, then UPDATE with `scored_candidates=n_written` and `status='COMPLETED'` (or
  `status='FAILED'` on exception).
- Rewrite `_check_candidate_coverage()` in `check_integrity.py` to LEFT JOIN from
  `learning_sweep_runs` rather than from model_observations — this makes zero-row cohorts visible.
- Cover OBSERVE, PAPER_ACTIVE, and SUSPENDED phases (remove `observation_phase = 'PAPER_ACTIVE'` filter).
- `compute_data_health()` should treat `status='FAILED'` or `scored_candidates < expected_candidates`
  as BLOCK for OBSERVE and PAPER_ACTIVE phases.

## Touches

- `agent_db.py` — migration for `learning_sweep_runs` table
- `agents/learning/challenger.py` — write sweep ledger record in `score_for_observe()`
- `check_integrity.py` — rewrite `_check_candidate_coverage()` to LEFT JOIN from ledger
- `agents/learning/calibration.py` — `compute_data_health()` checks sweep ledger failures
- `tests/test_calibration.py` — new tests for zero-row detection and OBSERVE phase coverage

## Done when

- [ ] `learning_sweep_runs` table exists and is written by `score_for_observe()` for every call
- [ ] A cohort where `scored_candidates = 0` is detected as BLOCK by the integrity audit
- [ ] OBSERVE and SUSPENDED phases are also validated (not just PAPER_ACTIVE)
- [ ] `compute_data_health()` flags FAILED sweep runs as BLOCK
