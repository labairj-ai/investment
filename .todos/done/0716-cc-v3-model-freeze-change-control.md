# Establish CC V3 Model Freeze and Change-Control Policy

- **ID:** 0716
- **Status:** backlog
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0711, 0712, 0713, 0714, 0715

## Problem

CC V3 now depends on accumulating prospective evidence over time. Frequent model or config changes can repeatedly invalidate simulator certification, open virtual chains, config hashes, paired cohorts, and promotion eligibility. At this stage, unnecessary model iteration can prevent the system from ever reaching the evidence thresholds required to determine whether V3 is better.

## Proposed approach

Create a documented and machine-readable **CC V3 Observation Freeze Policy** that classifies every change into one of three categories:

- **A. NON_BEHAVIORAL** (dashboard copy, docs, logging text, unrelated portfolio features): no model version bump, no simulator-contract reset, no prospective-cohort reset.
- **B. EVIDENCE_INFRASTRUCTURE** (reporting fixes, provenance fixes, accrual-health diagnostics, bug fixes that do not alter decisions): version evidence contract if needed; preserve economic model version when behavior is unchanged; document whether historical evidence remains eligible.
- **C. BEHAVIORAL_MODEL_CHANGE** (utility weights, overwrite policy, drift model, ranking surface, path-risk, duration flexibility, management policy, virtual fill model, tax economics): increment model/simulator/config contract; invalidate old promotion eligibility for the new version; apply 0712 open-chain censor policy; start new prospective cohort; require a written change manifest (reason, hypothesis, affected components, expected decision impact, motivating evidence, version changes, cohort-reset decision, open-chain impact, operator acknowledgment).

Add CI/release checks against simulator/model-relevant contract hashes:
- Behaviorally relevant hash change without version bump → fail CI.
- Behaviorally relevant hash change without change manifest → fail CI.
- Declared non-behavioral change that unexpectedly changes behavior contract hash → fail CI.

## Touches

- CI configuration
- `covered_call_validation.py` (contract hash checks)
- Change manifest schema/template
- Learning Lab dashboard (current experiment version, prospective cohort start date, days since last behavioral reset, reset count)
- Deployment checklist / runbook
- Tests

## Done when

- [ ] Dashboard text change is non-behavioral and does not change model contract
- [ ] Utility formula change requires model version bump and fails CI without it
- [ ] Management-policy change requires simulator contract/version handling and change manifest
- [ ] CI fails when a relevant hash changes without a version bump or manifest
- [ ] CI fails when a declared non-behavioral change unexpectedly changes the behavior hash
- [ ] Behavioral change starts a new eligible prospective cohort; prior evidence remains queryable under old version and does not silently qualify the new version
- [ ] Learning Lab shows current experiment version, cohort start date, days since last behavioral reset, and reset count
- [ ] Deployment checklist asks whether the release changes V3 behavior and requires operator acknowledgment for behavioral releases
