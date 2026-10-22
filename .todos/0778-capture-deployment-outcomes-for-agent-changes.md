# Capture Deployment Outcomes for Agent Changes

- **ID:** 0778
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0770, 0771, 0775

## Problem

A continuous-improvement agent cannot learn whether changes were useful if its feedback loop ends when a PR merges. Deployment and post-deploy health must be linked back to the exact candidate and SHA.

## Scope and acceptance

- [ ] Define deployment outcome records linking candidate/TODO/PR/merge SHA to deployed SHA, deployment time, environment and verification receipts.
- [ ] Capture post-deploy states such as `HEALTHY`, `DEGRADED`, `ROLLED_BACK`, `NOT_DEPLOYED` and `INSUFFICIENT_DATA` with evidence.
- [ ] Collect bounded operational metrics relevant to the change: errors, latency, failed jobs, canary status and feature-specific telemetry when explicitly defined by the TODO.
- [ ] Record rollback cause and target SHA when rollback occurs.
- [ ] Do not declare success merely because deployment completed; require the TODO-specific observation window or explicit human acceptance.
- [ ] Preserve immutable linkage from observed production state to the exact implementation SHA.
- [ ] Support manual outcome annotations for UX/usability changes that cannot be measured automatically.

## QA requirements

- [ ] Tests cover successful deployment, failed deploy, rollback, partial telemetry and stale/mismatched SHA.
- [ ] Production verification remains read-only except for the normal authorized deploy mechanism.
- [ ] Full suite passes.

## Implementation guardrails

- Do not use investment return performance as a software deployment metric unless a future explicitly designed experiment requires it.
- Missing telemetry means `INSUFFICIENT_DATA`, not healthy.
- Outcome capture must not trigger deployment.

## Numbering history

Renumbered from coding-agent task 0763 to 0778; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/outcomes.py: observe`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
