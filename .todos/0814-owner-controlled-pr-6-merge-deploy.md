# TODO 0814 — Merge and Deploy PR #6 Using Owner-Controlled Workflow

- **ID:** 0814
- **Status:** backlog
- **Created:** 2026-10-22
- **Priority:** high
- **Depends:** 0813

## Problem

Once PR #6 satisfies revised solo-owner governance, merge and deploy it through the normal human-controlled workflow rather than an exception path.

## Scope and acceptance

- [ ] Human owner performs merge.
- [ ] Record GitHub merge commit SHA and confirm it exists on main.
- [ ] Deploy merged main SHA to OptiPlex, not the pre-merge PR branch SHA as final release.
- [ ] Verify service active, Investment Dashboard healthy and Development Agent dashboard healthy.
- [ ] Verify authentication healthy and unauthorized Development Agent API requests denied.
- [ ] Require Advisor canary PASS and read-only mutation safety PASS.
- [ ] Verify holdings unchanged and development ledger unchanged except expected deployment/governance evidence.
- [ ] Verify autonomous implementation disabled and auto-merge disabled.
- [ ] Record deployment receipt against exact merge SHA.
- [ ] Preserve rollback backup.

## QA requirements

- [ ] Deployed SHA equals GitHub merge SHA.
- [ ] Production holdings unchanged.
- [ ] No execution/paper-intent policy changed.
- [ ] Development Agent autonomy remains disabled.
- [ ] Post-deploy status HEALTHY.

## Implementation guardrails

- Owner merge does not authorize future autonomous merges.
- This closes PR #6 only; it does not certify 0800 or enable 0801/0802.

## Implementation status — 2026-10-22

Exact-merge-SHA handoff and deployment/rollback checklist prepared. No owner merge observed and no new deployment performed; actual production acceptance remains open.
