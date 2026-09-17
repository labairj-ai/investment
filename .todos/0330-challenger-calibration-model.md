# Build Challenger Calibration Model for Score Adjustment

- **ID:** 0330
- **Status:** done
- **Created:** 2026-09-15
- **Priority:** normal
- **Depends:** 0329

## Problem

The base scoring formula (Buffett quality + valuation + portfolio fit + catalyst + evidence) was designed by hand. There is no mechanism to discover that certain component combinations predict better or worse actual alpha than the composite score implies, or that LLM conviction adds noise rather than signal. Without a data-driven challenger, the formula stays permanently frozen regardless of what the accumulated episode dataset reveals.

## Proposed approach

- Create `agents/learning/calibration.py` with a `ChallengerModel` that trains on labeled `decision_episodes` + `episode_outcomes` (90d alpha as primary label).
- Use shrinkage/regularized linear regression (ridge or elastic net) initially — not neural nets. Financial observations are correlated and sample sizes will be small for a long time; simple models with shrinkage generalize better in this regime.
- Model outputs per candidate: `expected_alpha` (float), `p_outperform` (0–1 probability vs SPY), `reliability` (shrinkage weight based on n observations), `learning_adjustment` (bounded score delta), `model_version` (str).
- Shrinkage formula: `adjustment = (n / (n + λ)) * empirical_adjustment` where λ ≈ 50. At n=5 observations, learner barely moves the score. At n=100, it has substantial influence.
- Cap the learning adjustment: `bounded_adjustment = clip(learning_adjustment, -10, +10)`. The learner can improve ranking but cannot overwhelm Buffett quality, valuation, or portfolio fit.
- Effective score: `S_effective = S_base + bounded_adjustment`. Hard risk limits remain entirely outside this path.
- Validate with chronological walk-forward splits — never random train/test splits (random splits leak future regime information into training).
- Persist trained model artifacts to `learning_models` table with training_cutoff, feature_schema_hash, training_n, validation_metrics_json.
- Challenger influences AGENTIC_ALPACA_01 paper trades only — champion (base score only) is the control. Compare cumulative alpha, drawdown, hit rate, and calibration between the two.

**Open questions:**
- What minimum training_n before the challenger is allowed to influence any paper trade at all (suggested: 30)?
- Should sizing multiplier (0.75×–1.25×) be introduced simultaneously or as a separate follow-on item?
- How are SHADOW_AUTO vs USER_ACCEPTED decision_origin rows weighted differently in training?

## Touches

- `agents/learning/calibration.py` — new file
- `agents/learning/challenger.py` — new file (loads latest model version, scores a candidate set)
- `agents/opportunity_agent.py` — read challenger score after base scoring, apply bounded adjustment
- `db/learning_models` — already created in 0327 migration
- `tests/` — unit tests for shrinkage formula, walk-forward split logic, cap enforcement, and that hard risk limits are unaffected

## Done when

- [ ] `ChallengerModel.train()` fits on labeled episodes with chronological walk-forward validation and persists artifact to `learning_models`
- [ ] `ChallengerModel.score()` returns `expected_alpha`, `p_outperform`, `reliability`, `learning_adjustment`, `model_version` for a candidate
- [ ] Bounded adjustment `clip(-10, +10)` is enforced before any score delta is applied
- [ ] Shrinkage formula reduces adjustment toward zero when training_n < 30; adjustment is suppressed entirely below minimum threshold
- [ ] Hard risk rules in the risk engine are not modified and have no awareness of the challenger
- [ ] Walk-forward validation metrics are recorded in `learning_models` and visible in Learning Lab (0329)
- [ ] All existing unit and integration tests pass

## Outcome

Implemented in commit a7202de. Ridge regression via numpy normal equations (sklearn not installed). Features: q_score, v_score, pf_score, c_score, ec_score → 90d SPY alpha. Shrinkage: `reliability = n / (n + 50.0)`, adjustment capped at ±10 score points. Chronological walk-forward split (first 80% train, last 20% validate). Model persisted to `learning_models` table via `save_with_weights()` (coef/intercept stored in validation_metrics JSON). `challenger.py` has module-level model cache. opportunity_agent.py wired: adjustment applied after scoring loop, before sort; no-op when training_n < 30 or no model. 12 calibration tests + 756 total pass. **Today the model is inactive** (0 labeled 3m episodes). Will auto-activate once 30 labeled episodes exist, after 90+ days of episode accumulation.
