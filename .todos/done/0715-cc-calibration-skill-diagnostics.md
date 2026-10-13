# Add CC Calibration Skill Diagnostics Against Naive References

- **ID:** 0715
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** normal
- **Depends:** 0701, 0713

## Problem

Current promotion calibration uses an absolute Brier-score ceiling. Absolute Brier score alone does not show whether the V3 probability model is better than a simple reference forecast such as historical base rate or entry-delta/moneyness cohort frequency. Without a skill score, a passing Brier may still reflect a model that adds no value over a naive baseline.

## Proposed approach

Add diagnostic-only reference forecasts (diagnostic only — must not alter the current promotion gate):

- Events: strike touch, regret-barrier touch, delta ≥ 0.30, delta ≥ 0.50.
- Primary reference: `BASE_RATE_BY_DTE_OTM_BUCKET` precommitted with shrinkage to global CC event frequency.
- Secondary reference: entry-delta proxy (reported separately).
- Compute `Brier Skill Score = 1 − BS_model / BS_reference` for each event.
- Persist: model Brier, reference Brier, Brier Skill Score, reference version, reference sample N, shrinkage parameters, confidence/eligibility state.
- Add reliability tables/plots when sample size supports them.
- Negative skill must be shown, not clipped to zero.
- Predefine the primary reference before reviewing final skill results (no cherry-picking).

## Touches

- Calibration module (wherever Brier score is computed today)
- DB schema (reference Brier, skill score, reference version columns)
- Learning Lab dashboard (Brier and Brier Skill side by side, reference definition, low-N state)
- Tests

## Done when

- [ ] Brier Skill Score is computed and persisted for each calibration event
- [ ] Perfect model yields BSS near 1; model equal to reference yields BSS near 0; worse model yields negative BSS
- [ ] Zero reference Brier is handled explicitly without division error
- [ ] Reference frequency uses only outcomes known before each evaluated decision (no lookahead)
- [ ] Below minimum N, shrunk reference is used or marked insufficient; raw low-N frequency is not treated as stable truth
- [ ] Dashboard shows Brier and Brier Skill side by side with reference definition and low-N state visible
- [ ] Negative skill is visibly negative in the dashboard
- [ ] Promotion eligibility is unchanged — no new skill metric can block or permit promotion
