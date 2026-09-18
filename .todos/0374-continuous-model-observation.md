# Write Prediction Observations for OBSERVE, PAPER_ACTIVE, and SUSPENDED Models

- **ID:** 0374
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0373

## Problem

The 0371 degradation monitor queries `model_observations` to assess a PAPER_ACTIVE
model's ongoing edge. But `model_observations` is only populated for OBSERVE-state
models via `score_for_observe()`. Once a model is promoted to PAPER_ACTIVE, no new
observation rows are written — the monitor is therefore evaluating the model's
OBSERVE-era predictions as those outcomes mature, rather than continuously measuring
new decisions made while the model is active.

Additionally, Opportunity Hunter only invokes `score_for_observe()` for models in
`lifecycle_state = 'OBSERVE'`, so SUSPENDED models never write the recovery evidence
the spec says they should.

## Proposed approach

- Add `observation_phase TEXT` to `model_observations` (values: `OBSERVE`,
  `PAPER_ACTIVE`, `SUSPENDED`) set at write time from the model's current state
- Change Opportunity Hunter (or the observation-writing call site) to invoke
  `score_for_observe()` for all three states: `OBSERVE`, `PAPER_ACTIVE`, `SUSPENDED`
- Update `score_for_observe()` to pass `lifecycle_state` through to the INSERT so
  `observation_phase` is populated correctly
- `_check_degradation()` should specifically evaluate rows with
  `observation_phase = 'PAPER_ACTIVE'` to distinguish post-promotion performance
  from qualification-period evidence. It may also calculate a
  `paper_active_era_n` count to require a minimum window of live observations
  before triggering a suspension verdict.
- `compute_prospective_metrics()` can report breakdowns by phase for transparency

Open question: should PAPER_ACTIVE model observations also suppress the challenger
adjustment (since the challenger adjustment IS the model's prediction), or should
the observation record the counterfactual prediction independently?

## Touches

- `agent_db.py` — `_new_cols`: `observation_phase TEXT` on `model_observations`
- `agents/learning/challenger.py` — `score_for_observe()`: pass phase; expand lifecycle
  state filter from `('OBSERVE', 'SUSPENDED')` to include `'PAPER_ACTIVE'`
- `agents/opportunity_agent.py` (or equivalent Opportunity Hunter call site) — invoke
  `score_for_observe()` for PAPER_ACTIVE and SUSPENDED models, not only OBSERVE
- `agents/learning/calibration.py` — `_check_degradation()`: filter on
  `observation_phase = 'PAPER_ACTIVE'`
- `tests/test_calibration.py` — test that PAPER_ACTIVE model writes new observations;
  test that degradation evaluates only PAPER_ACTIVE-phase rows

## Done when

- [ ] `observation_phase` column on `model_observations` populated at write time
- [ ] PAPER_ACTIVE models write new observation rows on every Opportunity Hunter cycle
- [ ] SUSPENDED models continue writing observation rows (for recovery audit)
- [ ] `_check_degradation()` evaluates only `observation_phase='PAPER_ACTIVE'` rows
- [ ] Test: promote model → confirm new observations appear with phase=PAPER_ACTIVE
- [ ] Test: suspend model → confirm observations continue with phase=SUSPENDED
- [ ] `python -m pytest tests/` passes with no regressions
