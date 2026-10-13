# Stabilize Covered Call Physical Drift and Probability Estimation

- **ID:** 0691
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0690

## Problem

The current physical-return drift estimate heavily weights recent realized returns and then uses a single point estimate inside `itm_prob_real`, `regret_prob`, expected upside surrendered, and `cc_alpha`.

Expected return is much noisier than volatility. A strongly negative or positive short-term drift estimate can therefore create false precision, including effectively zero regret probabilities, even when meaningful path risk remains.

## Proposed approach

Replace the single drift point estimate with a shrinkage model that produces both a center estimate and uncertainty.

Inputs should include:

- long-run market/asset prior
- 252-session return estimate
- shorter-term momentum/regime signal
- estimation uncertainty / effective sample size

Persist:

- `mu_center`
- `mu_low`
- `mu_high`
- `drift_model_version`

For upside-risk quantities compute both base and conservative values:

- `itm_prob_real_base`
- `itm_prob_real_conservative`
- `regret_prob_base`
- `regret_prob_conservative`
- `cc_alpha_base`
- `cc_alpha_conservative`

Conservative upside-risk estimates should use either posterior integration or the upper drift bound rather than assuming the point estimate is known.

Use conservative values for hard risk gates; keep both for diagnostics.

## Guardrails

- Do not let short-term momentum alone determine expected return.
- Do not hard-code zero drift.
- Do not remove the existing historical-volatility model in this TODO.
- Keep all calculations deterministic for the same input data and model version.

## Done when

- [ ] Extreme 60-session returns cannot independently create near-zero risk outputs without a correspondingly strong posterior.
- [ ] Drift outputs include uncertainty bounds.
- [ ] Base and conservative regret/ITM/alpha values are persisted.
- [ ] Synthetic tests cover strong positive, flat, and strong negative recent-return regimes.
- [ ] Rankings are stable under small drift perturbations.
- [ ] Model version and all inputs needed to reproduce drift are captured.
- [ ] No production influence is added outside existing entry scoring until 0694.
