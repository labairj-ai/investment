# Enable Bounded L0–L2 Autonomous Implementation-to-PR

- **ID:** 0794
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0793

## Problem

After successful supervised evidence, the development agent can begin bounded autonomous implementation, but only within low-risk classes and only through PR creation.

Autonomy must not expand into merge, deployment, financial decision logic or account mutation.

## Scope and acceptance

- [ ] Require current eligibility from:
  - technical certification
  - authentic production-snapshot safety check
  - GitHub effective-protection PASS
  - minimum supervised successes
  - minimum seven-day observation period
  - current harness/config/contracts hash
- [ ] Enable autonomous candidate progression only for L0–L2.
- [ ] L3 remains human-started.
- [ ] L4/L5 remain prohibited from generic autonomous Builder execution.
- [ ] Autonomous scope may include:
  - documentation
  - tests
  - presentation/mobile/accessibility
  - read-only analytics/UI within explicitly approved low-risk surfaces
- [ ] Autonomous agent may:
  - identify candidate
  - score candidate
  - create approved-policy plan
  - create isolated worktree
  - implement
  - validate
  - undergo independent review
  - open/update PR
- [ ] Autonomous agent may not:
  - merge
  - deploy
  - modify GitHub rulesets
  - alter credentials
  - modify authoritative investment data
  - call brokers
  - change financial logic
  - approve its own risk escalation
- [ ] Require bounded daily implementation volume.
- [ ] Add emergency kill switch/config disable path.
- [ ] Any certification/protection failure immediately disables autonomous starts.
- [ ] In-progress work may fail closed to `NEEDS_HUMAN`.

## QA requirements

- [ ] L0 autonomous candidate can reach PR-ready state.
- [ ] L2 autonomous candidate can reach PR-ready state.
- [ ] L3 candidate stops for human authorization.
- [ ] L4/L5 candidate cannot enter generic Builder.
- [ ] Disabled config prevents new autonomous starts immediately.
- [ ] Expired/stale certification prevents new autonomous starts.
- [ ] Protection failure prevents new autonomous starts.
- [ ] Autonomous run cannot merge or deploy.
- [ ] Full suite, canary and adversarial certification pass.

## Implementation guardrails

- Human merge remains permanent for this phase.
- Auto-merge remains false.
- Do not automatically raise autonomous risk ceiling based on successful history.
- Any future expansion beyond L0–L2 requires a separate reviewed TODO and prospective evidence.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.

## Implementation progress — 2026-10-22

Implementation: `dev_agent/autonomy.py; dev_agent/operations.py; config/development_agent.json`. Built bounded implementation-to-PR progression for frozen human-approved L0–L2 scopes, daily reservation, current technical/protection/history gates and immediate emergency-disable handling. No self-approval, merge, deployment, protection change or financial autonomy. Configuration remains disabled; new Scout proposals still need explicit scope approval.

See [hardening plan](../docs/plans/development-agent-hardening-0785-0794.md),
[operator contract](../docs/development-agent.md) and
[prospective pilot protocol](../docs/development-agent-pilots.md).

Focused, adversarial and browser results are recorded in the PR evidence.
Acceptance remains open pending exact-head CI, unchanged release/CC gates and
applicable operational evidence. Current main reproduces seven CC contract/test
failures. Docker is unavailable on this development machine; GitHub main has no
classic protection or active rules. No live pilot, production backup authenticity,
physical-device acceptance or autonomy activation is claimed. No TODO is moved to
done based solely on fixture success.
