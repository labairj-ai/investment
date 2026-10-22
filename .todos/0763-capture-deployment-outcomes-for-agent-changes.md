# Capture Deployment Outcomes for Agent Changes

- **ID:** 0763
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0755, 0756, 0760

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

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
