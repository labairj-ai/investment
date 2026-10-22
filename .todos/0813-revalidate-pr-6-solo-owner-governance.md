# TODO 0813 — Revalidate PR #6 Under Solo-Owner Governance

- **ID:** 0813
- **Status:** backlog
- **Created:** 2026-10-22
- **Priority:** critical
- **Depends:** 0810, 0811, 0812
- **Blocks:** PR #6 merge

## Problem

PR #6 has green CI but no qualifying review under the existing governance model. After migration it must satisfy the new policy, without automatic grandfathering.

## Scope and acceptance

- [ ] Confirm PR #6 remains open and unmerged.
- [ ] Rebase/update PR #6 onto governance-enabled main if necessary.
- [ ] Resolve conflicts without unintended investment behavior changes.
- [ ] Run full exact-head CI and require current PR-head CI PASS.
- [ ] Require covered-call behavioral contract, Development Agent governance and release-baseline gates PASS.
- [ ] Repository owner reviews the complete PR #6 diff.
- [ ] Record explicit owner approval against exact current head SHA.
- [ ] Record rationale that this is a solo-owner project and the owner personally reviewed the change.
- [ ] Verify no autonomous approval/merge event contributed to authorization.
- [ ] Verify compliance with risk-specific governance policy.

## QA requirements

- [ ] Exact current head SHA is green.
- [ ] Owner approval references that same SHA.
- [ ] No stale prior evidence is accepted.
- [ ] PR remains human-merge only.
- [ ] No autonomy configuration changes occur in PR #6.

## Implementation guardrails

- Do not accept the previously green bad4491e... run if PR #6 head changes.
- Re-run everything after governance/rebase changes.

## Implementation status — 2026-10-22

Read-only handoff validator prepared. PR #6 remains open; governance-enabled main, updated exact-head CI and actual owner review are prerequisites. The existing bad4491e run is historical if the head changes.
