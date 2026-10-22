# Surface Real Coding-Agent Certification and Readiness in the Dashboard

- **ID:** 0791
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0776, 0777, 0785, 0786, 0787, 0788, 0790

## Problem

The Development Agent dashboard currently exposes placeholder values such as `certification="NOT_RUN"` and `autonomous_implementation=false`.

Operators need a trustworthy view of what remains before supervised or autonomous operation is permitted.

## Scope and acceptance

- [ ] Compute dashboard readiness from real config, certificates, ledger events and GitHub protection state.
- [ ] Display:
  - harness hash
  - technical certification
  - sandbox runtime status
  - production snapshot provenance status
  - GitHub protection status
  - supervised successes completed / required
  - first/last qualifying supervised run
  - observation days elapsed / required
  - autonomous implementation enabled/disabled
  - auto-merge status
  - scheduled discovery status
- [ ] Distinguish:
  - `READY_FOR_SUPERVISED`
  - `SUPERVISED_ONLY`
  - `AUTONOMY_ELIGIBLE`
  - `BLOCKED`
  - `UNAVAILABLE`
- [ ] Show specific blockers rather than a single generic status.
- [ ] Show when prior certification became stale because harness/config changed.
- [ ] Do not expose authentication secrets, model prompts or unrestricted logs.
- [ ] Keep mobile presentation usable at 360–430px.
- [ ] Preserve separation between software-development state and investment recommendations.

## QA requirements

- [ ] Empty/new installation renders accurately.
- [ ] Partial certification displays exact blockers.
- [ ] Three qualifying runs over fewer than seven days does not show autonomy eligible.
- [ ] Sufficient runs with stale harness hash does not show autonomy eligible.
- [ ] Fully qualifying fixture state renders eligible only when autonomy config permits.
- [ ] Mobile accessibility/browser tests pass.
- [ ] Read-only dashboard access does not mutate the ledger.

## Implementation guardrails

- Dashboard is observational except existing explicit human decision endpoints.
- UI cannot override a failing technical gate.
- Do not convert `UNAVAILABLE` to a reassuring visual PASS state.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.

## Implementation progress — 2026-10-22

Implementation: `dev_agent/readiness.py; dev_agent/dashboard.py`. Read-only actual readiness projection with exact blockers, stale/expired certification, sandbox/backup/protection evidence, qualifying pilot count/dates, calendar-day progress, disabled autonomy and auto-merge. Browser coverage includes 360/390/430/1280px.

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
