# Build Daily Outcome Labeler for Episode Dataset

- **ID:** 0328
- **Status:** in-progress
- **Created:** 2026-09-15
- **Priority:** normal
- **Depends:** 0327

## Problem

`decision_episodes` rows captured by 0327 are permanently unlabeled without a job that attaches retrospective market outcomes. Without labels, the episode dataset cannot be used for model training, calibration, or any statistical analysis. The existing OutcomeEvaluator logic covers accepted recommendations only, waits 14 days, and is not wired to episodes — it cannot serve this role.

## Proposed approach

- Create `agents/learning/outcome_labeler.py` with a `label_mature_episodes()` function meant to run once per day after market close.
- For each unlabeled `decision_episodes` row whose `timestamp` is at least 7 days old, fetch the price series for the ticker and SPY, compute return at each horizon (1w, 1m, 3m, 6m, 12m where data exists), derive alpha = ticker_return − spy_return, MAE (max adverse excursion), and MFE (max favorable excursion) over each window, and INSERT into `episode_outcomes`.
- Also label `risk_counterfactual_outcomes` rows for intents that were risk-blocked — same price/benchmark logic.
- Reuse the price-fetching infrastructure already present in the OutcomeEvaluator / portfolio_ai rather than writing a new data path.
- Add a systemd timer or cron on Optiplex to invoke this daily (e.g. 6pm ET).
- 1-week results are diagnostic only; 1-month and 3-month are the primary ML labels.

**Open questions:**
- Should labeling be skipped for tickers with < N trading days of history at the horizon?
- How to handle tickers that get delisted or acquired before a horizon completes?

## Touches

- `agents/learning/outcome_labeler.py` — new file
- `db/migrations/` — none needed if 0327 migration already created `episode_outcomes`
- `systemd/` or cron on Optiplex — new timer unit
- `tests/` — unit tests with mock price data, verify horizon math and SPY alpha calculation

## Done when

- [ ] `label_mature_episodes()` inserts `episode_outcomes` rows for all episodes ≥ 7 days old at each available horizon
- [ ] SPY alpha, MAE, and MFE are computed correctly against price series
- [ ] Risk-blocked counterfactuals in `risk_counterfactual_outcomes` are labeled by the same logic
- [ ] Existing episodes are not re-labeled if an outcome row already exists for that episode_id + horizon
- [ ] Daily systemd timer fires after market close on Optiplex
- [ ] Unit tests pass with mock prices; integration test verifies at least one real episode gets labeled end-to-end
