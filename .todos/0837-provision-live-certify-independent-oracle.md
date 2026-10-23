# TODO 0837 — Provision and Live-Certify Independent Oracle

- **ID:** 0837
- **Status:** backlog
- **Priority:** critical
- **Risk:** L5
- **Parent:** 0826
- **Depends:** 0836
- **Blocks:** 0841

## Objective

Install the reviewed oracle on OptiPlex and produce the first non-fixture certification.

## Provisioning

- [ ] Dedicated runtime/service identity.
- [ ] Controller outside candidate worktree.
- [ ] Private socket/API.
- [ ] Private signing/HMAC material.
- [ ] Key permissions verified.
- [ ] Pinned runtime/image.
- [ ] No inherited owner credentials.
- [ ] No production investment-data access.
- [ ] Resource/time limits configured.

## Live acceptance

Run:

- [ ] clean passing candidate;
- [ ] known failing candidate;
- [ ] complete adversarial suite from 0836;
- [ ] timeout cleanup;
- [ ] crash recovery;
- [ ] host-source integrity check;
- [ ] residual-process/container check.

## Certificate requirements

Produce non-fixture certificate containing:

- harness hash;
- oracle version;
- runtime/image digest;
- created timestamp;
- expiration;
- adversarial matrix;
- trusted inventory digest;
- artifact-integrity PASS.

## Guardrails

No supervised Builder may start until this certificate is current and PASS.

## Done when

0826 can legitimately close.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.
