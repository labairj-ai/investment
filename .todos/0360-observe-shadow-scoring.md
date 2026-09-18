# OBSERVE State: Real Shadow Scoring with Prospective Outcomes

- **ID:** 0360
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0355

## Problem

The OBSERVE lifecycle state currently provides no meaningful observation. `challenger.get_model()` loads only PAPER_ACTIVE models — TRAINED and OBSERVE models have no influence on scoring. So during the 14-day OBSERVE window:

```
New episode arrives
      ↓
OBSERVE model does NOT score it
      ↓
fresh_episodes count += 1
```

The OBSERVE→PAPER_ACTIVE gate checks that five fresh episodes *existed* while the model sat, not that the model *predicted* them. Worse, because the primary learning target is 3-month alpha, a 14-day window cannot contain mature outcomes for those episodes anyway.

This means promoting to PAPER_ACTIVE is gated on calendar time and data arrival rate, not on any evidence about the model's prospective predictive ability.

## Proposed approach

### New table: `model_observations`

```sql
CREATE TABLE IF NOT EXISTS model_observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    ticker TEXT NOT NULL,
    prediction_timestamp TEXT NOT NULL,
    base_score REAL,
    predicted_alpha REAL,
    learning_adjustment REAL,
    challenger_score REAL,
    would_select INTEGER,  -- 1 if model would have picked this ticker
    outcome_alpha_90d REAL,  -- populated later by outcome_labeler
    outcome_labeled_at TEXT,
    UNIQUE(model_version, episode_id)
);
```

### `challenger.py` — shadow scoring for OBSERVE models

Add `score_for_observe(model_version, candidates)` that:
1. Loads the specific OBSERVE model (bypassing the PAPER_ACTIVE filter)
2. Scores every candidate
3. Writes one `model_observations` row per candidate
4. Returns nothing — zero influence on rankings or decisions

This function is called from `opportunity_agent.py` after the main scoring pass, for any model currently in LIFECYCLE_OBSERVE state.

### `outcome_labeler.py` — populate `model_observations.outcome_alpha_90d`

When labeling `decision_episodes`, also look up any `model_observations` rows for the same `episode_id` and populate `outcome_alpha_90d` once the 90-day horizon matures.

### Updated OBSERVE→PAPER_ACTIVE gate (0355 addendum)

Replace or supplement the `fresh_episodes_since_observe` gate with:
- `mature_observations >= OBSERVE_MIN_MATURE_OBS` (e.g., 5): model must have at least N predictions with mature 90-day outcomes
- `observation_hit_rate > 0.0` or similar directional accuracy check: model's `would_select=1` predictions outperformed base-score selections on those episodes

For the first iteration, require `mature_observations >= 5` and block on `INSUFFICIENT_OBSERVATION_DATA` if not met. Directional accuracy check can come later.

### `_check_promotion_gates()` update

Add to OBSERVE→PAPER_ACTIVE gates:
```python
mature_obs = conn.execute(
    "SELECT COUNT(*) FROM model_observations WHERE model_version=? AND outcome_alpha_90d IS NOT NULL",
    (model_version,)
).fetchone()[0]
gates["mature_observations"] = {
    "value": mature_obs, "minimum": OBSERVE_MIN_MATURE_OBS,
    "pass": mature_obs >= OBSERVE_MIN_MATURE_OBS,
}
```

## Touches

- `agent_db.py` — migrate: add `model_observations` table
- `agents/learning/calibration.py` — `_check_promotion_gates()` adds `mature_observations` gate; define `OBSERVE_MIN_MATURE_OBS = 5`
- `agents/learning/challenger.py` — `score_for_observe(model_version, candidates)` shadow-scores without influencing decisions
- `agents/opportunity_agent.py` — call `score_for_observe()` for any LIFECYCLE_OBSERVE model after main scoring
- `agents/learning/outcome_labeler.py` — populate `model_observations.outcome_alpha_90d` for matured episodes
- `tests/test_calibration.py` — `TestObserveShadowScoring0360`: assert OBSERVE model writes observations; assert gate blocks when mature_observations < threshold; assert gate passes after labeler populates outcomes

## Done when

- [ ] `model_observations` table exists with schema above
- [ ] OBSERVE-state model scores every candidate without altering rankings; writes one row per candidate per episode
- [ ] `outcome_labeler.py` fills `outcome_alpha_90d` on mature observations
- [ ] OBSERVE→PAPER_ACTIVE gate requires `mature_observations >= 5` (not just calendar time + data count)
- [ ] Test: OBSERVE model scores 6 episodes, 5 are labeled → gate passes; only 4 labeled → gate fails
- [ ] `python -m pytest tests/` passes with no regressions
