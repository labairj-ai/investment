# Full Regression and Live Canary Audit

- **ID:** 0423
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0418, 0419, 0420, 0421, 0422

## Problem

Recent development has run `tests/test_calibration.py` (216 tests) rather than the full
repo-wide discovery suite (~1000 tests). The learning pipeline changes in 0411-0417 touch
agent_db.py, opportunity_agent.py, calibration.py, challenger.py, and check_integrity.py —
all of which are exercised by tests outside the calibration suite. Until the full suite is
verified green, there is no regression guarantee. Additionally, no live end-to-end canary has
been run on Optiplex to confirm the deployed pipeline actually executes correctly against real
market data.

## Proposed approach

Part 1 — Full regression:
- Run `pytest` (or `python -m pytest`) from the repo root with no path filter on Optiplex.
- Confirm the ~1000-test suite passes with no new failures.
- Fix any regressions before declaring the learning subsystem frozen.

Part 2 — Live canary audit (run one real OH sweep, then verify from DB):
1. Trigger one Opportunity Hunter run on Optiplex (or wait for scheduled run).
2. Query the DB and assert:
   - All candidate tickers appear in `decision_episodes` for the run's `run_id`.
   - `learning_sweep_runs` expected_candidates == scored_candidates for each model (0418 required first).
   - Exactly one `model_observations` row has `would_select=1` for each model/cohort.
   - Exactly one `model_observations` row has `base_would_select=1` for each model/cohort.
   - A `decision_variants` row exists with `challenger_episode_id` matching the `would_select=1`
     observation's `episode_id`.
   - `check_integrity.run_integrity_audit()` returns `overall == 'ok'` (or only known-acceptable WARNs).
3. Document the canary results (pass/fail per assertion) before stopping architecture work.

## Touches

- No code changes expected — this is a verification and canary exercise.
- If regressions are found, fix them as part of this ticket.
- Shell script or ad-hoc SQL for canary assertions could be written to `scripts/canary_audit.sh`.

## Done when

- [ ] Full ~1000-test pytest suite passes green on Optiplex (or Mac mini)
- [ ] One live OH sweep executed and all canary DB assertions pass
- [ ] `run_integrity_audit()` returns no BLOCK after the live canary sweep
- [ ] Canary results documented (even informally in a commit message or comment)
