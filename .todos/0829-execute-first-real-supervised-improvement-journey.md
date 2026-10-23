# TODO 0829 — Execute First Real Supervised Improvement Journey

- **ID:** 0829
- **Status:** in-progress
- **Priority:** critical strategic
- **Risk:** L3 — supervised agent software development
- **Depends:** 0826, 0827, 0828
- **Blocks:** 0831

## Problem

The Development Agent has not yet demonstrated a genuine production-connected end-to-end software-improvement journey using the newly deployed control plane.

The first journey should prove the system can take a real low-risk problem from discovery to a reviewed PR while stopping for owner authorization.

## Candidate requirements

Select one real candidate that is:

- L0 or L1 preferred;
- non-financial;
- non-authentication;
- non-governance;
- non-deployment;
- small and reversible;
- externally verifiable.

Preferred examples:

- documentation defect;
- low-risk test improvement;
- inaccessible label;
- passive UI correction;
- safe dashboard presentation issue.

## Activation

For this pilot:

- [ ] set `supervised_loop_enabled=true` through a separate reviewed owner-approved activation change;
- [ ] keep `autonomous_implementation=false`;
- [ ] keep `supervised_publish_pr` according to pilot stage;
- [ ] keep `auto_merge=false`.

## Required journey

The system must perform:

`signal`
→ `DISCOVERED`
→ `PLANNED`
→ `APPROVED_FOR_BUILD`
→ `BUILDING`
→ `REVIEWING`
→ `VALIDATING`
→ `PR_READY`
→ `AWAITING_OWNER`

without manual coding intervention.

## Required evidence

- [ ] Candidate source/provenance.
- [ ] Deterministic risk classification.
- [ ] Frozen TODO/plan.
- [ ] Build-policy admission.
- [ ] Isolated worktree.
- [ ] Builder identity.
- [ ] Reviewer identity distinct from Builder.
- [ ] Builder actions.
- [ ] Reviewer findings.
- [ ] Correction iteration if applicable.
- [ ] Independent oracle validation.
- [ ] Focused tests.
- [ ] Full regression suite.
- [ ] Release gates.
- [ ] Exact candidate SHA.
- [ ] PR number/head.
- [ ] No merge authority granted.

## Owner checkpoint

At `AWAITING_OWNER`:

- [ ] ChatGPT reviews actual diff and evidence.
- [ ] Owner says OK/NO.
- [ ] 0827 owner gateway records exact-head decision.
- [ ] Only OK may permit merge.
- [ ] NO returns candidate to appropriate state.
- [ ] Changed head requires fresh owner decision.

## Safety acceptance

- [ ] Builder cannot edit governance.
- [ ] Builder cannot edit deployment subsystem.
- [ ] Builder cannot edit financial logic.
- [ ] Builder cannot push main.
- [ ] Builder cannot merge.
- [ ] Builder cannot deploy.
- [ ] Increased deterministic risk stops the run.
- [ ] Validation failure stops the run.
- [ ] Reviewer high-severity finding stops progression.

## Done when

- [ ] One genuine candidate reaches `AWAITING_OWNER` automatically.
- [ ] Owner OK/NO flow succeeds.
- [ ] PR merges only after exact-head OK.
- [ ] Pilot is ready for deployment-agent validation.

## Implementation / acceptance handoff — 2026-10-23

Existing supervised pipeline stays gated on live prerequisites and separate activation. Successful qualification now requires a valid bound Deployment Agent receipt. No real pilot or Builder run occurred.

See [live operational acceptance](../docs/live-operational-acceptance.md) and the [sanitized live preflight](../docs/evidence/continuous-improvement-20261023/live-acceptance-preflight.json). This task remains in progress until every required live acceptance and release gate is satisfied.
