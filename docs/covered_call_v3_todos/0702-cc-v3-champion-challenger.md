# Covered Call V3 Champion/Challenger and Promotion Gate

- **ID:** 0702
- **Status:** pending
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0700, 0701

## Problem

Recent poor covered-call outcomes are not sufficient evidence to replace the current production policy. A new model could overfit the recent market regime.

V3 must prove that it improves economic outcomes and/or management burden prospectively before gaining production influence.

## Proposed approach

Keep the current V2 selection path as champion.

Run V3 in observe-only challenger mode for every eligible CC decision.

Capture both:

- write vs NO_CALL
- recommended overwrite fraction
- contract
- expected premium
- expected alpha
- expected management risk
- expected tax/execution cost
- rank/reason

Classify divergence:

- SAME_NO_CALL
- SAME_CONTRACT
- CHAMPION_CALL_CHALLENGER_NO_CALL
- CHALLENGER_CALL_CHAMPION_NO_CALL
- DIFFERENT_STRIKE
- DIFFERENT_EXPIRY
- DIFFERENT_COVERAGE
- MULTI_DIMENSION_DIVERGENCE

Primary evaluation should include:

- incremental alpha vs hold
- total covered-position return
- roll frequency
- management cost
- upside surrendered
- assignment-policy violations
- realized execution cost
- calibration quality

Define promotion policy before looking at final results.

Require:

- prospective evidence
- minimum N
- sufficient divergent decisions
- no material safety/policy regression
- reproducible scorer/config/model versions

## Guardrails

- Retrospective backtests alone cannot promote V3.
- Challenger must have zero production influence initially.
- No free-form LLM learning or weight mutation.
- Promotion must be a versioned, reversible config/state transition.
- A weak or inconclusive result means remain observe-only.

## Done when

- [ ] V2 champion and V3 challenger run on the same decision opportunities.
- [ ] Divergence classes are persisted.
- [ ] Prospective evaluation excludes non-independent duplicate decisions where appropriate.
- [ ] Promotion policy and minimum-N thresholds are committed before eligibility.
- [ ] V3 cannot influence production before the promotion gate passes.
- [ ] Promotion snapshot records git SHA, config versions, scorer versions, cohort evidence, and sample counts.
- [ ] Rollback to V2 is one explicit state/config change.
