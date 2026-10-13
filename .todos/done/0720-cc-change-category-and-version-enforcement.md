# Enforce CC Change Category and Component-Specific Version Semantics

- **ID:** 0720
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0719

## Problem

0716 defines `NON_BEHAVIORAL`, `EVIDENCE_INFRASTRUCTURE`, and `BEHAVIORAL_MODEL_CHANGE`, but the checker does not enforce the declared category.

The current `version_bumped` logic is also too broad: changing any one of model version, simulator version, or simulator contract version counts as a bump, even when a different component actually changed.

## Proposed approach

Machine-enforce category semantics.

### NON_BEHAVIORAL

- engine hash unchanged
- simulator contract hash unchanged
- behavioral versions unchanged
- no cohort reset
- no open-chain censoring caused by the release

### EVIDENCE_INFRASTRUCTURE

- decision/management behavior hashes unchanged
- economic model and simulator behavior versions unchanged
- evidence/reporting schema versions may change
- eligibility impact explicitly declared

### BEHAVIORAL_MODEL_CHANGE

- exact 0719 transition manifest
- component-appropriate version bump(s)
- cohort reset semantics
- 0712 open-chain handling when simulator behavior changes
- no inheritance of old promotion eligibility

Component-level rules:

- management/virtual execution behavior => simulator contract version bump
- ranking/economic model => model/config version bump
- cadence certification policy => cadence/validation policy bump
- multi-component change => all applicable bumps

## Implementation guardrails

- Unrelated version bump cannot satisfy changed component.
- Declared category never overrides hash evidence.
- Non-behavioral change must not reset cohort.
- Behavioral change must not preserve old promotion eligibility.
- Evidence-infrastructure changes must not silently alter decisions.
- Category mismatch fails with a specific reason.
- V3 remains observe-only.

## Touches

- `covered_call_change_control.py`
- 0719 manifest schema/template
- `scripts/check_cc_contract.py`
- version constants/config contracts
- tests
- deployment docs

## Acceptance tests

- [ ] Dashboard/docs change declared NON_BEHAVIORAL passes with unchanged hashes.
- [ ] NON_BEHAVIORAL declaration with changed engine/simulator hash fails.
- [ ] Evidence/reporting-only change passes as EVIDENCE_INFRASTRUCTURE.
- [ ] Evidence-infrastructure declaration that changes recommendation behavior fails.
- [ ] Management-policy change requires simulator contract version bump.
- [ ] Fill-model change requires simulator contract version bump.
- [ ] Utility/ranking change requires model/config bump.
- [ ] Cadence policy change requires cadence policy bump.
- [ ] Management change plus only model-version bump fails.
- [ ] Ranking change plus only simulator bump fails when model/config bump is required.
- [ ] Multi-component change requires all applicable bumps.
- [ ] Behavioral change starts new eligible cohort.
- [ ] Old cohort remains queryable but cannot qualify new version.
- [ ] Simulator behavior change applies 0712 open-chain censor policy.
- [ ] Non-behavioral change preserves cohort continuity.

## QA requirements

- [ ] Add table-driven tests for every category/component combination.
- [ ] Error output names changed component and required version.
- [ ] Exercise one disposable release of each category in CI.
- [ ] Verify misclassification fails.
- [ ] Verify wrong-component version bump fails.
- [ ] Verify correct behavioral transition + exact manifest + correct bumps passes.
- [ ] Dashboard/deploy output states category and reset/censor impact.

## Done when

- [ ] Change categories are machine-enforced
- [ ] Version bumps are component-specific
- [ ] Misclassified changes fail CI
- [ ] Evidence resets only when behavior actually changes
