# TODO 0834 — Cross-Bind Deployment Evidence Before Candidate State Advancement

- **ID:** 0834
- **Status:** done
- **Priority:** high
- **Risk:** L5 — release evidence / state-machine integrity
- **Depends:** deployment evidence schema, observer implementation
- **Blocks:** PR #13 merge, 0830 completion, 0831 qualifying runs
- **Scope:** deployment evidence and signed software observation integrity

## Problem

An internally valid normalized envelope can be paired with the wrong private transaction or candidate observation. record_success() currently verifies the candidate binding after DEPLOYED/OBSERVING advancement. Validate before signing HEALTHY and before any candidate success-state mutation.

## Observer binding

Before HEALTHY signing, require valid embedded deployment-evidence-1 and:

- [x] Embedded repository, PR, head and merge match the outer transaction.
- [x] Embedded deployed SHA matches actual observed HEAD.
- [x] Embedded main SHA matches the authorized outer main SHA.
- [x] Actor is deployment-agent, fixture_only=false, and evidence originated from a successful fixed-controller transaction.
- [x] Mismatch cannot sign HEALTHY; fail closed/degrade and preserve private failure evidence without normalizing away invalid evidence.

## Candidate admission binding and atomicity

Before DEPLOYED/OBSERVING or any success-state mutation:

- [x] Verify HMAC and observation repository, PR, candidate head, merge and deployed SHA.
- [x] Validate embedded schema/digest and repository, PR, head, merge, deployed and main identity against actual candidate/PR/merge.
- [x] Use qualifying() or an equivalent candidate-specific check before mutation.
- [x] Reject cross-candidate/PR/repository replay and ambiguity.
- [x] Malformed/mismatched data leaves candidate state and event inventory unchanged: no DEPLOYED/OBSERVING, OPERATIONAL_SUCCESS or qualifying-run record. An immutable security rejection is permitted, never success advancement.

## Required adversarial tests

- [x] Correctly signed outer PR A with internally valid inner PR B rejects without mutation.
- [x] Wrong head, merge, deployed SHA or repository rejects without mutation.
- [x] Fixture and manual-owner-authorized evidence cannot qualify; PR10 remains valid historical evidence only.
- [x] Digest consistency alone never substitutes for identity.
- [x] Cross-candidate, cross-PR and cross-repository replay tests assert state/event invariance.
- [x] Valid complete signed observation progresses DEPLOYMENT_PENDING → DEPLOYED → OBSERVING → CLOSED only after all identity checks.
- [x] Observer valid evidence signs HEALTHY; invalid evidence cannot.
- [x] Wrong actual HEAD, health failure or protected-state mismatch remains DEGRADED, never HEALTHY.
- [x] Existing deployment/signed-observation tests remain green; full release suite passes.

## Guardrails

Do not weaken signature checks, trust paths/filenames as identity, accept internally consistent digests as sufficient identity, count manual PR10 as a supervised controller release, or enable deployment.

## Done when

- [x] Inner/outer evidence are internally/cryptographically valid and identity-consistent.
- [x] Candidate qualification precedes advancement; mismatch causes zero success-state mutation.
- [x] Focused/full tests and exact-head CI pass.

## Implementation and validation evidence

- Implemented on PR #13 from verified starting head `df64c4e5813d1cf2fe675d7358e940d3c2b5e3aa`.
- Validated final application code head: `07875aad350b3b1dad113b74cd029db382bae79b`.
- [Exact-head CI PASS](https://github.com/labairj-ai/investment/actions/runs/40014960716): all eight mandatory gates PASS.
- Focused agent suite: 379 passed. Full suite: 3,078 passed, zero failed, 18 existing skips.
- New scheduler/shared-gate/observer adversarial tests: 84 passed in disposable ledgers. No synthetic evidence was issued as a live certificate or operational success.
- All seven requested policy settings remain unchanged; no financial source, investment state, production data, service or timer was changed.
- Owner promotion is an explicitly unavailable authenticated interface, not a completed issuer; config cannot activate runtime. 0826–0831 remain open for their actual live acceptance.
- PR #13 remains draft, and PR #12 is not merged separately.
