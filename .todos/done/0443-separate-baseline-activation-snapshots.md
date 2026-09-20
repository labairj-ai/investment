# Separate Baseline from Model Activation Snapshots

- **ID:** 0443
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** normal
- **Depends:** 0442

## Problem

`config/experiment_baseline.json` is meant to be immutable — it records the
strategy/policy/environment conditions before any model was activated. But the
commit message for 0442 says to re-run `freeze_baseline.py` once a model reaches
OBSERVE/PAPER_ACTIVE, which would overwrite the immutable record and destroy the
pre-learner baseline. A separate artifact is needed to capture per-model activation
state (git SHA, promotion metrics, evidence contract, etc.) at each lifecycle
transition rather than conflating it with the experiment baseline.

## Proposed approach

- Remove (or correct) the conflicting guidance in `scripts/freeze_baseline.py`
  that suggests re-running at model activation; add a clear comment that it is
  frozen once per experiment.
- Add model-activation snapshots at each OBSERVE and PAPER_ACTIVE promotion event.
  Options: extend `model_promotion_log` table with extra columns (git_sha,
  strategy_hash, policy_hash, evidence_contract_version, training_config_hash,
  promotion_metrics_json), or add a dedicated `model_activation_snapshots` table.
  Question: extend model_promotion_log (less schema churn) or add new table
  (cleaner separation)? Extending model_promotion_log seems simpler.
- Write the activation snapshot in `calibration.promote()` (and the re-entry path
  for SUSPENDED → OBSERVE) alongside the existing promotion logic.
- Surface the latest activation snapshot in `/api/learning/readiness` so the
  dashboard shows what conditions were in place when the active model was promoted.

## Touches

- `scripts/freeze_baseline.py` (remove conflicting rerun guidance)
- `agents/learning/calibration.py` (promote() path writes activation snapshot)
- `agent_db.py` (schema: extend model_promotion_log or add model_activation_snapshots)
- `serve.py` (surface latest activation snapshot in readiness report)

## Done when

- [ ] `freeze_baseline.py` contains no instruction to re-run at model activation
- [ ] Each OBSERVE/PAPER_ACTIVE promotion writes a snapshot with git SHA, strategy hash, policy hash, evidence contract version, and promotion metrics
- [ ] `experiment_baseline.json` is never touched by the promotion path
- [ ] Latest activation snapshot is visible in `/api/learning/readiness`
