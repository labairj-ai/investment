# Enforce CC Manifest Semantic Values and Complete Transition Identity

- **ID:** 0725
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0719, 0720, 0724

## Problem

Populated manifest strings currently qualify without semantic validation, and policy/cadence identities are omitted from transition matching.

## Implementation guardrails and acceptance

- [ ] Allow only NON_BEHAVIORAL, EVIDENCE_INFRASTRUCTURE, BEHAVIORAL_MODEL_CHANGE.
- [ ] Parse actual booleans; reject unknown spellings, require operator acknowledgment and behavioral cohort_reset_required=true.
- [ ] Validate open_chain_policy against the 0712 VERSION_CENSORED policy; unknown/missing policy cannot authorize simulator change.
- [ ] Bind prior/proposed model, simulator, simulator contract versions, engine/simulator hashes, policy and cadence policy versions.
- [ ] Template contains every machine-required field; templates never authorize transitions.
- [ ] Duplicate IDs and duplicate exact applicable transitions remain failures. Invalid semantic findings name field and expected values.
- [ ] Use table-driven invalid-value and complete identity tests. Migration is deterministic: old incomplete manifests remain readable but cannot authorize a new full-identity transition.
- [ ] No economics changes. Run parser, focused/adversarial, full suite and release gate.

## Completion

Pending full QA and actual GitHub Actions verification.
