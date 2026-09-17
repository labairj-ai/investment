# True Champion/Challenger Experiment: Parallel Decisions, Alpaca Paper Only

- **ID:** 0336
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0331, 0335

## Problem

The current challenger implementation has a critical architectural flaw: `apply_challenger_adjustment()` is called inside the general Opportunity Hunter scoring loop and overwrites `_composite` before the candidate list is sorted. This changes the recommendation ranking itself regardless of which trading account will receive the trade. The base strategy is no longer a clean control.

The design intent from 0330 was explicit: *"Challenger influences AGENTIC_ALPACA_01 paper trades only — champion (base score only) is the control."* That intent is not implemented. If the learned model starts changing the same recommendations that generate its future training data, there is no clean champion/control and the experiment is confounded.

The correct design:
- **Champion**: base formula score unchanged. Champion recommendations are what the system would have done without any learned adjustment.
- **Challenger**: a parallel decision variant derived from the champion recommendation, applying the bounded adjustment, created specifically for the Alpaca paper account.
- The champion and challenger share the same candidate set and the same risk engine; only the score (and therefore rank/selection) differs.

## Proposed approach

**Remove challenger adjustment from base scoring loop:**
- Delete or stub `apply_challenger_adjustment()` from `agents/opportunity_agent.py`. The base `_composite` score must never be modified by the challenger.
- The sort, selection, and champion recommendation generation run entirely on base scores.

**Introduce `decision_variant` table (or extend existing schema):**
- `id`, `recommendation_id` (FK), `episode_id` (FK), `origin TEXT` (e.g. `PAPER_CHALLENGER`)
- `challenger_score REAL`, `challenger_model_version TEXT`, `challenger_adjustment REAL`
- `variant_action`, `variant_confidence`, `variant_rationale` — if challenger would have selected a different candidate, record what it would have done
- `created_at`

**Challenger variant generation (after champion selection):**
- After the base Opportunity Hunter run produces champion recommendations, run a second pass over the same candidate set applying challenger scores.
- For each candidate where `lifecycle_state == PAPER_ACTIVE`, compute challenger-adjusted score and determine if challenger would rank/select differently from the champion.
- Insert a `decision_variant` row for each candidate where challenger score differs materially from champion score, and for any candidate the challenger would have selected but the champion did not (or vice versa).

**Intent routing by account:**
- `IntentBuilder` for the AGENTIC_ALPACA_01 account must pull from challenger variants (via `decision_variant`) rather than champion recommendations.
- `decision_origin` on the resulting `TradeIntent` is set to `PAPER_CHALLENGER`.
- All other accounts (manual, other paper accounts) use champion recommendations only.

**Dashboard — champion vs challenger comparison:**
- Add a comparison section to Learning Lab showing, over the same calendar period:
  - Champion vs challenger alpha (SPY-relative)
  - Champion vs challenger drawdown
  - Champion vs challenger hit rate (% trades with positive alpha)
  - Champion vs challenger MAE and MFE
  - Champion vs challenger portfolio turnover
- Data source: `trade_outcomes` joined on `decision_origin` (0333 required).

**Training data integrity:**
- Champion episodes feed challenger training. Challenger-origin paper fills are labeled separately as `EXECUTED_TRADE_RETURN` with `decision_origin = PAPER_CHALLENGER`.
- The challenger model must NOT be trained on its own execution outcomes to avoid feedback loops (for now). Restrict training to champion episodes with `COUNTERFACTUAL_SIGNAL_RETURN` labels.

## Touches

- `agents/opportunity_agent.py` — remove `apply_challenger_adjustment()` from base scoring loop; add challenger-variant pass after champion selection
- `db/migrations/` — new `decision_variants` table
- `agent_db.py` — insert/read helpers for `decision_variants`
- `trade_engine/intent_builder.py` — route AGENTIC_ALPACA_01 intents to challenger variants; set `decision_origin = PAPER_CHALLENGER`
- `agents/learning/calibration.py` — restrict training corpus to champion-origin episodes
- `generate_dashboard.py` / `serve.py` — champion vs challenger comparison panel in Learning Lab
- `tests/` — assert base score unchanged after challenger pass; assert challenger variants recorded; assert PAPER_CHALLENGER intents use variant scores; assert training excludes challenger-origin fills

## Outcome

6 files changed. `agent_db.py`: `decision_variants` table added (episode_id, origin, challenger_model_version, challenger_score, challenger_adjustment, would_have_selected, champion_ticker, variant_ticker, created_at). `opportunity_agent.py`: `_composite_challenger` and `_challenger_info` stored on each candidate separately from `_composite` (base score never mutated); `_insert_decision_variant()` called after champion selection when challenger is PAPER_ACTIVE; inserts one row recording which ticker the challenger would have picked and whether it matches the champion. `trade_engine/intent_builder.py`: for ALPACA accounts, checks `decision_variants WHERE episode_id=? AND origin='PAPER_CHALLENGER'`; sets `decision_origin='PAPER_CHALLENGER'` if a variant row exists, else `'CHAMPION'`. `serve.py`: `_handle_champion_challenger()` method added for `GET /api/learning/champion-challenger`; queries `trade_outcomes JOIN trade_intents` grouped by `decision_origin`; returns alpha_mean, hit_rate, mae_mean, mfe_mean, return_mean for champion and challenger separately, plus variant_count, variants_would_diverge, and active model metadata. Training corpus isolation is architectural: `episode_outcomes` uses market-close prices only; challenger fills go to `trade_outcomes` exclusively; no feedback loop possible. `tests/test_calibration.py`: `TestChampionChallengerExperiment0336` class with 5 tests: base composite unchanged, variants recorded when PAPER_ACTIVE, no variants when inactive, CHAMPION origin when no variant, PAPER_CHALLENGER origin when variant exists. 783 passed, 16 skipped.

## Done when

- [x] `apply_challenger_adjustment()` no longer modifies `_composite` in the base scoring loop; base recommendations use only formula scores
- [x] Challenger variant pass runs after champion selection and inserts `decision_variants` rows for the active paper challenger
- [x] AGENTIC_ALPACA_01 `IntentBuilder` routes to challenger variants with `decision_origin = PAPER_CHALLENGER`; all other accounts use champion recommendations
- [x] Champion-origin and challenger-origin paper fills are separately labeled in `trade_outcomes`
- [x] Challenger training corpus restricted to champion-origin episodes (no feedback loop)
- [x] Dashboard shows champion vs challenger alpha, hit rate, MAE/MFE side-by-side
- [x] `python -m pytest tests/` passes with no regressions
