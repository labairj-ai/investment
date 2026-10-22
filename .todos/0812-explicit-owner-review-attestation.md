# TODO 0812 — Add Explicit Owner Review Attestation

- **ID:** 0812
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** high
- **Depends:** 0811
- **Blocks:** PR #6 merge

## Problem

The same GitHub identity may author and approve a change in a solo-owner repository. Evidence must demonstrate a deliberate review action rather than treating authorship as approval.

## Scope and acceptance

- [ ] Define an explicit owner-review event.
- [ ] Bind review to repository, PR number, exact head SHA, risk level, review timestamp, authenticated owner identity, decision and rationale where required.
- [ ] Support APPROVE, REQUEST_CHANGES and DEFER decisions.
- [ ] Require rationale for L3+ approval.
- [ ] Require financial-review acknowledgment for L4 approval.
- [ ] Require execution-risk acknowledgment for L5 approval.
- [ ] Invalidate prior exact-head approval when new PR commits arrive.
- [ ] Display owner-review state on Development Agent dashboard where applicable.
- [ ] Keep owner review separate from Builder/Reviewer model evidence.

## QA requirements

- [ ] Authorship alone does not count as approval.
- [ ] Explicit owner approval does count.
- [ ] Approval for SHA A does not authorize SHA B.
- [ ] Agent cannot manufacture an owner-review event.
- [ ] Replayed approval nonce is rejected.
- [ ] Audit ledger clearly identifies owner approval source.

## Implementation guardrails

- Owner approval is an intentional human act.
- Do not automatically approve PRs after green CI.

## Implementation status — 2026-10-22

Attestation ledger, replay/stale-head denial, operator CLI, trusted-proxy API and dashboard audit history implemented. No real owner approval is synthesized; operator identity provisioning and actual human acceptance remain pending.
