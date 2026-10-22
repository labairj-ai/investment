# TODO 0810 — Adopt Solo-Owner Governance Model

- **ID:** 0810
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** none
- **Blocks:** PR #6 merge, 0811, 0812

## Problem

The repository currently requires an independent human reviewer and prohibits self-approval. That assumes a multi-person team; this personal project has one human owner. The safety boundary is human-versus-agent authority, not author-versus-reviewer identity.

## Scope and acceptance

- [ ] Replace the multi-human review requirement with a solo-owner governance model.
- [ ] Define the repository owner as an authorized human reviewer and approver.
- [ ] Explicitly permit owner approval of changes authored through the owner's own GitHub account.
- [ ] Define independence: the coding agent cannot approve its own work; reviewer models, CI and autonomous workflows cannot grant merge authority; the human repository owner retains final merge authority.
- [ ] Make a second human reviewer optional unless explicitly designated by the owner for a specific change.
- [ ] Preserve stronger financial/execution requirements.
- [ ] Preserve auto_merge=false and required_human_merge=true.
- [ ] Preserve prohibition on autonomous agent merges.
- [ ] Record an intentional owner governance decision, not a temporary PR #6 exception.

## Proposed governance language

For this personal repository, the repository owner may serve as the human reviewer and approver for changes, including changes authored through the owner's GitHub account.

"Independent review" means that an AI coding agent, reviewer model, automated workflow, or other non-human process may not approve or authorize its own changes.

A second human reviewer is not required unless the repository owner explicitly designates one for a particular change. The repository owner must explicitly review and approve changes before merge where human approval is required.

Additional safeguards apply by risk level:

- L0–L2: owner review plus required CI/evidence.
- L3: explicit owner review and rationale.
- L4: explicit owner financial-domain review plus financial canaries, behavioral-contract evidence and applicable observation gates.
- L5: explicit owner approval plus execution/account-mutation safeguards and required deployment confirmation.

Automated systems may recommend, test, review or prepare PRs, but may not approve, merge, deploy, lower safety gates or alter governance requirements on their own.

## QA requirements

- [ ] Documentation distinguishes human owner authority from agent authority.
- [ ] No language permits agent self-approval or enables auto-merge.
- [ ] No financial/execution gate is weakened.
- [ ] Governance checks recognize owner approval as valid human approval.

## Implementation guardrails

- Do not create a one-off exemption for PR #6.
- Do not redefine AI reviewer output as human review.
- Do not remove human merge requirements.

## Implementation status — 2026-10-22

Permanent owner policy and static guard prepared in a main-based foundation branch; owner adoption/merge remains pending.
