# Model Lifecycle Governance: TRAINED → OBSERVE → PAPER_ACTIVE → RETIRED

- **ID:** 0335
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0334

## Problem

The current activation rule is `training_n >= 30 → active`. This is wrong on two counts:

1. Raw row count is not a meaningful readiness gate (see 0334).
2. `train_and_save()` and `load_latest()` exist, but there is no trainer timer or scheduled invocation anywhere in the codebase or on the Optiplex. The model will not retrain automatically when new labeled episodes accumulate — it requires a manual call. Yet if that call is eventually automated, the current code makes activation implicit the moment training runs.

**Training should be automatic. Promotion must not be automatic.**

The concept of "crossing 30 rows → active" must be eliminated and replaced with an explicit lifecycle with human/policy promotion.

## Proposed approach

**Model lifecycle states** (add `lifecycle_state` column to `learning_models`):
- `TRAINED` — model was fit and its validation metrics recorded. It does not influence any decision.
- `OBSERVE` — model scores candidates and its predictions are logged alongside base scores, but it does not alter `_composite` or any ranked list. Purely observational.
- `PAPER_ACTIVE` — model applies bounded adjustment to the challenger paper account only (see 0336 for the champion/challenger split). Requires explicit promotion gate (human confirmation or automated policy once 0336 is complete).
- `RETIRED` — superseded by a newer model version; kept for audit.

**Promotion gates (not thresholds — checklist):**
A model cannot advance from TRAINED → OBSERVE or OBSERVE → PAPER_ACTIVE without all applicable gates passing:

| Gate | Metric |
|------|--------|
| Data coverage | `unique_tickers`, `unique_decision_dates`, `unique_weeks` meet configured minimums |
| Temporal coverage | Elapsed calendar period since first training episode ≥ configured minimum |
| Baseline improvement | Cross-validated MAE beats null-model MAE |
| Ranking value | `top_vs_bottom_quintile_alpha` > 0 |
| Directional stability | No coefficient sign reversals across majority of folds |
| Economic value | (PAPER_ACTIVE only) Challenger paper alpha ≥ champion over same period |
| Safety | Zero modification of deterministic risk policy rules |

Gate thresholds are config-driven (not hardcoded) and recorded as a JSON checklist in `learning_models.promotion_gates_json`.

**Scheduled retraining:**
- Add a systemd timer on the Optiplex (or launchd on Mac if dev only) to invoke `calibration.py train` nightly. Training is always allowed; promotion is not.
- Newly trained models start in `TRAINED` state regardless of metrics.

**Challenger influence gated by state:**
- `challenger.py` must check `lifecycle_state` before returning any adjustment. If state is not `PAPER_ACTIVE`, return zero adjustment and null model version.
- The opportunity agent must never apply an adjustment from a model in `TRAINED` or `OBSERVE` state.

**Remove implicit activation:**
- Delete all code paths that check `training_n >= 30` to decide whether to apply an adjustment.

**LLM conviction — fix missing write:**
- `mark_episode_selected()` writes `selected` and `llm_why` but never writes `conviction`. The LLM Conviction card in Learning Lab reads `llm_conviction` but it is always NULL.
- Fix `mark_episode_selected()` (and/or the opportunity agent caller) to write `llm_conviction` from the LLM response at episode-capture time.

## Touches

- `db/migrations/` — add `lifecycle_state TEXT`, `promotion_gates_json TEXT` to `learning_models`
- `agents/learning/calibration.py` — `train_and_save()` writes `lifecycle_state = 'TRAINED'`; add `promote()` function that validates gates and advances state
- `agents/learning/challenger.py` — gate adjustment on `lifecycle_state == 'PAPER_ACTIVE'`
- `agents/opportunity_agent.py` — remove `training_n >= 30` check; remove any implicit activation logic; write `llm_conviction` at episode capture
- `agent_db.py` — `mark_episode_selected()` writes `llm_conviction`
- Optiplex systemd / cron — nightly retraining timer that calls `calibration.py train` (TRAINED state only)
- `tests/` — assert model in TRAINED/OBSERVE returns zero adjustment; assert promotion gates checked; assert llm_conviction populated

## Done when

- [ ] `learning_models` has `lifecycle_state` and `promotion_gates_json` columns; `train_and_save()` writes `TRAINED`
- [ ] `challenger.py` returns zero adjustment for any model not in `PAPER_ACTIVE` state
- [ ] All `training_n >= 30` implicit activation logic removed from opportunity agent and challenger
- [ ] `promote()` function validates all configured gates before advancing lifecycle state; gates recorded in `promotion_gates_json`
- [ ] Scheduled retraining timer configured on Optiplex (TRAINED state only, never auto-promotes)
- [ ] `mark_episode_selected()` writes `llm_conviction`; LLM Conviction card in Learning Lab shows non-NULL values after next episode capture run
- [ ] `python -m pytest tests/` passes with no regressions
