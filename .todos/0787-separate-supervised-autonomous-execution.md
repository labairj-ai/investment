# Separate Supervised and Autonomous Coding-Agent Execution Modes

- **ID:** 0787
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0767, 0783, 0784, 0785

## Problem

The current Runner requires `certification.current()` before a build can start, while `certification.current()` requires autonomous implementation to be enabled.

This creates a circular dependency: real supervised coding runs are needed to earn autonomy certification, but the supported build path is blocked until autonomy is certified.

## Scope and acceptance

- [ ] Introduce explicit execution modes:
  - `SUPERVISED`
  - `AUTONOMOUS`
- [ ] Supervised mode requires an explicit human-approved candidate and explicit human invocation.
- [ ] Supervised mode requires:
  - approved frozen scope
  - exact approved base SHA
  - current technical certification
  - verified workspace isolation
  - GitHub safety/protection requirements appropriate to supervised operation
- [ ] Supervised mode must not require the accumulated autonomous certification threshold.
- [ ] Autonomous mode must continue to require:
  - configured autonomy enablement
  - current harness hash
  - minimum supervised successes
  - minimum observation period
  - current technical certification
  - GitHub protections
  - all other safety gates
- [ ] Record execution mode in every run, iteration, evidence receipt and PR.
- [ ] A supervised run may never silently count as autonomous.
- [ ] An autonomous run may never fall back to supervised behavior without human authorization.
- [ ] High-risk L4/L5 financial/execution work remains unavailable to the generic autonomous Builder.
- [ ] `autonomous_implementation=false` must continue to block autonomous initiation.

## QA requirements

- [ ] Supervised approved L0–L2 task can run while autonomous implementation is false.
- [ ] Autonomous task cannot run while autonomous implementation is false.
- [ ] Autonomous task cannot run with insufficient supervised history.
- [ ] L4/L5 task cannot enter autonomous Builder even with full certification.
- [ ] Mode survives crashes/recovery and is visible in audit history.
- [ ] Changing mode after approval requires a new authorization event.
- [ ] Full suite passes.

## Implementation guardrails

- Supervised does not mean unrestricted.
- Do not weaken the Builder sandbox in supervised mode.
- Human initiation does not waive validation, review or evidence requirements.
- Merge and deployment remain separately authorized.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.
