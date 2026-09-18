# Monitor PAPER_ACTIVE Model for Edge Degradation and Auto-Suspend

- **ID:** 0371
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0365

## Problem

The current governance answers "how does a model become active?" but not "how
does an active model lose permission when its edge disappears?" A PAPER_ACTIVE
model is promoted once and then assumed good forever. Financial regimes change:
correlations shift, data distributions drift, and a model's ranking quality
can silently erode without any signal. Without a degradation monitor, the
champion/challenger experiment could run for months accumulating unreliable
experiment data from a model that stopped working.

## Proposed approach

### Rolling performance tracking

After each batch of `model_observations` outcomes matures, recompute a rolling
window of prospective metrics (same set as 0365):

```
rolling_window = last 30 mature observations (configurable)
metrics = selection_alpha_spread, prediction_mae, prospective_hit_rate
```

Write these to a new table `model_performance_snapshots`:

```sql
CREATE TABLE IF NOT EXISTS model_performance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    window_n INTEGER,
    selection_alpha_spread REAL,
    prediction_mae REAL,
    baseline_mae REAL,
    prospective_hit_rate REAL,
    edge_verdict TEXT,  -- POSITIVE / INCONCLUSIVE / NEGATIVE
    UNIQUE(model_version, snapshot_date)
);
```

### Auto-suspend rule

After each snapshot computation, if:
```
edge_verdict == NEGATIVE for 2 consecutive snapshots
OR selection_alpha_spread < 0 for 3 consecutive snapshots
```

automatically move the model to `SUSPENDED` lifecycle state:
- Stop calling `challenger.py` to apply its adjustments
- Preserve model weights and all history (do not delete)
- Write a `model_promotion_log` entry with `from_state=PAPER_ACTIVE`,
  `to_state=SUSPENDED`, `reason="auto_degradation"`, plus the triggering
  snapshot metrics

### SUSPENDED state behavior

- `score_for_observe()` continues writing shadow observations (cheap; valuable for retrospective audit)
- `challenger.py` `get_adjustment()` returns 0.0 for SUSPENDED models
- A SUSPENDED model can be manually re-promoted to OBSERVE (not directly to
  PAPER_ACTIVE) by an operator with `override_reason`

### Dashboard visibility

Surface the rolling snapshot in the Learning Lab card (from 0370). Show a
simple sparkline of `selection_alpha_spread` over time per model version.

### Open questions

- Should the snapshot window be 30 observations or 30 calendar days? Observations are more
  meaningful but accumulate slowly. Calendar days could be too sparse.
- Should the threshold be configurable in `strategy.json` or hardcoded for now?

## Touches

- `agents/learning/calibration.py` — `LIFECYCLE_SUSPENDED` constant; `_check_degradation()` computes rolling metrics and auto-suspends; `score_for_observe()` path not blocked for SUSPENDED
- `agents/learning/challenger.py` — returns 0.0 adjustment for SUSPENDED models
- `agents/learning/outcome_labeler.py` — trigger `_check_degradation()` after back-filling outcomes
- `agent_db.py` — `model_performance_snapshots` table; `LIFECYCLE_SUSPENDED` state allowed in `learning_models`
- `tests/test_calibration.py` — test that 2 consecutive NEGATIVE snapshots trigger SUSPENDED; test that SUSPENDED model returns 0 adjustment; test that observer still writes observations for SUSPENDED model

## Done when

- [ ] `model_performance_snapshots` table exists and is populated after each labeling batch
- [ ] `LIFECYCLE_SUSPENDED` state defined and handled in `get_adjustment()` (returns 0.0)
- [ ] 2 consecutive NEGATIVE rolling snapshots automatically move model to SUSPENDED
- [ ] `model_promotion_log` entry written at suspension with triggering metrics
- [ ] SUSPENDED model can be manually re-promoted to OBSERVE (not PAPER_ACTIVE) with override_reason
- [ ] Test: feed 2 consecutive negative snapshots → model transitions to SUSPENDED
- [ ] Test: SUSPENDED model challenger adjustment = 0.0
- [ ] Test: SUSPENDED model still receives shadow observations
- [ ] `python -m pytest tests/` passes with no regressions
