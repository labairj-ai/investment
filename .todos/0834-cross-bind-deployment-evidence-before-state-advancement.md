# TODO 0834 — Cross-Bind Deployment Evidence Before Candidate State Advancement

- **ID:** 0834
- **Status:** in-progress
- **Priority:** high
- **Risk:** L5 — release evidence / state-machine integrity
- **Depends:** deployment evidence schema, observer implementation
- **Blocks:** PR #13 merge, 0830 completion, 0831 qualifying runs
- **Scope:** deployment evidence and signed software observation integrity

## Problem

An internally valid normalized envelope can be paired with the wrong private transaction or candidate observation. record_success() currently verifies the candidate binding after DEPLOYED/OBSERVING advancement. Validate before signing HEALTHY and before any candidate success-state mutation.

## Observer binding

Before HEALTHY signing, require valid embedded deployment-evidence-1 and:

- [ ] Embedded repository, PR, head and merge match the outer transaction.
- [ ] Embedded deployed SHA matches actual observed HEAD.
- [ ] Embedded main SHA matches the authorized outer main SHA.
- [ ] Actor is deployment-agent, fixture_only=false, and evidence originated from a successful fixed-controller transaction.
- [ ] Mismatch cannot sign HEALTHY; fail closed/degrade and preserve private failure evidence without normalizing away invalid evidence.

## Candidate admission binding and atomicity

Before DEPLOYED/OBSERVING or any success-state mutation:

- [ ] Verify HMAC and observation repository, PR, candidate head, merge and deployed SHA.
- [ ] Validate embedded schema/digest and repository, PR, head, merge, deployed and main identity against actual candidate/PR/merge.
- [ ] Use qualifying() or an equivalent candidate-specific check before mutation.
- [ ] Reject cross-candidate/PR/repository replay and ambiguity.
- [ ] Malformed/mismatched data leaves candidate state and event inventory unchanged: no DEPLOYED/OBSERVING, OPERATIONAL_SUCCESS or qualifying-run record. An immutable security rejection is permitted, never success advancement.

## Required adversarial tests

- [ ] Correctly signed outer PR A with internally valid inner PR B rejects without mutation.
- [ ] Wrong head, merge, deployed SHA or repository rejects without mutation.
- [ ] Fixture and manual-owner-authorized evidence cannot qualify; PR10 remains valid historical evidence only.
- [ ] Digest consistency alone never substitutes for identity.
- [ ] Cross-candidate, cross-PR and cross-repository replay tests assert state/event invariance.
- [ ] Valid complete signed observation progresses DEPLOYMENT_PENDING → DEPLOYED → OBSERVING → CLOSED only after all identity checks.
- [ ] Observer valid evidence signs HEALTHY; invalid evidence cannot.
- [ ] Wrong actual HEAD, health failure or protected-state mismatch remains DEGRADED, never HEALTHY.
- [ ] Existing deployment/signed-observation tests remain green; full release suite passes.

## Guardrails

Do not weaken signature checks, trust paths/filenames as identity, accept internally consistent digests as sufficient identity, count manual PR10 as a supervised controller release, or enable deployment.

## Done when

- [ ] Inner/outer evidence are internally/cryptographically valid and identity-consistent.
- [ ] Candidate qualification precedes advancement; mismatch causes zero success-state mutation.
- [ ] Focused/full tests and exact-head CI pass.
