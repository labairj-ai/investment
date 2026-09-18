# Add Session-Based Outcome Labels V2 Alongside Calendar Labels

- **ID:** 0369
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0361

## Problem

The learning target in `calibration.py` and `outcome_labeler.py` defines
horizons in calendar days (`91d = 3m`, `182d = 6m`, etc.), while the virtual
portfolio now exits after 63 NYSE trading sessions. These are usually
close but not identical — a week with a holiday adds a day to the calendar
horizon without adding a session — so the model is trained on a target that
does not match the experiment's exit condition.

The cleanest fix is to define all learning horizons in trading sessions
(`5/21/63/126/252`), but silently rewriting existing `decision_episodes` rows
would make old and new labels appear interchangeable when they were computed
differently.

## Proposed approach

### 1. Add `horizon_definition_version` to outcome label rows

Add a column to `decision_episodes` (or a separate `episode_outcomes` table)
that tags each outcome row with the definition used:

```
calendar_v1   — original calendar-day horizons (91d, 182d, etc.)
sessions_v2   — trading-session horizons (63 sessions = 3m, etc.)
```

No existing rows need to be rewritten. New labeling runs emit `sessions_v2`
rows alongside (or instead of) `calendar_v1` rows.

### 2. New session-based horizon constants

```python
HORIZONS_SESSIONS = {
    "1w":  5,
    "1m":  21,
    "3m":  63,
    "6m":  126,
    "12m": 252,
}
```

`outcome_labeler.py` counts NYSE sessions between the decision date and today
using `trading_sessions_between()` (already in `market_calendar.py` from 0361)
to determine when a horizon has matured.

### 3. Model training version flag

`calibration.py` should record which horizon definition the training run used
so that models trained on `calendar_v1` labels and models trained on
`sessions_v2` labels are never mixed in the same evaluation.

Add `training_horizon_version TEXT` to `learning_models`.

### Transition plan

- Leave existing `calendar_v1` rows intact; new `outcome_labeler` runs tag
  new rows `sessions_v2`
- Once the `sessions_v2` backlog has enough labeled rows (≥30 per horizon),
  `calibration.py` can default to training on `sessions_v2` only
- Do not delete `calendar_v1` rows; they remain auditable

### Open questions

- Should the labeler write both versions simultaneously, or only the current
  default? Writing both doubles label volume but simplifies rollback.
- At what point is `calendar_v1` training fully deprecated?

## Touches

- `agents/learning/outcome_labeler.py` — use `trading_sessions_between()` to detect mature horizons; tag rows with `horizon_definition_version`
- `agent_db.py` — add `horizon_definition_version TEXT` to `decision_episodes` or the outcomes table; add `training_horizon_version TEXT` to `learning_models` via `_new_cols`
- `agents/learning/calibration.py` — filter training rows by `horizon_definition_version`; record `training_horizon_version` on each trained model
- `trade_engine/market_calendar.py` — `trading_sessions_between()` already present (0361); confirm it handles edge cases (same-day, future end-date)
- `tests/test_calibration.py` — test that v1 and v2 labels are not mixed in training; test session-count maturity detection for each horizon

## Done when

- [ ] `horizon_definition_version` column exists on outcome rows; existing rows have `calendar_v1`
- [ ] New labeling runs produce `sessions_v2` rows using `trading_sessions_between()`
- [ ] `learning_models.training_horizon_version` recorded per trained model
- [ ] `calibration.py` never mixes `calendar_v1` and `sessions_v2` rows in a single training run
- [ ] Test: 63 sessions elapsed → 3m horizon matures under `sessions_v2`; same date range may not trigger under `calendar_v1`
- [ ] `python -m pytest tests/` passes with no regressions
