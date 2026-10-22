# Run and Evaluate Three Supervised Low-Risk Development-Agent Pilots

- **ID:** 0793
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0785, 0786, 0787, 0788, 0789, 0790, 0791, 0792

## Problem

Unit tests and fixture canaries cannot establish whether the coding-agent workflow works reliably on real repository tasks.

The system needs prospective supervised evidence before autonomy is enabled.

## Scope and acceptance

- [ ] Select three real L0–L2 development tasks.
- [ ] Prefer tasks such as:
  - documentation improvement
  - regression-test addition
  - accessibility improvement
  - read-only dashboard UX improvement
  - low-risk developer tooling
- [ ] Exclude financial scoring, risk, execution, brokerage, portfolio mutation and promotion behavior.
- [ ] For each pilot run the full lifecycle:
  - Scout/candidate
  - human candidate approval
  - plan
  - committed/frozen TODO
  - supervised worktree
  - Builder
  - independent Reviewer
  - trusted validation
  - sealed evidence
  - PR creation
  - remote SHA verification
  - human PR review
  - merge/deploy through existing human workflow if accepted
  - post-deploy observation
- [ ] Record reviewer findings, correction iterations, validation runtime, failures, human overrides and post-deployment results.
- [ ] Require three qualifying successes under the same harness hash.
- [ ] Span at least seven calendar days between earliest and latest qualifying evidence.
- [ ] Any harness/config/contract change that invalidates evidence resets eligibility according to policy.

## QA requirements

- [ ] Each run has complete immutable lineage.
- [ ] No run modifies protected investment logic.
- [ ] No bypass/override is required to obtain success.
- [ ] Every merged pilot has exact deployed-SHA observation.
- [ ] Any failed or rolled-back pilot remains visible and does not count as success.
- [ ] Dashboard reports progress accurately.

## Implementation guardrails

- Pilot goal is evidence collection, not maximizing task throughput.
- Do not cherry-pick only successes after the fact.
- Record failures honestly.
- Keep human merge authority.

## Source

Captured from the [shared hardening and rollout plan](https://chatgpt.com/s/t_6ad9755089988191970329e796b72a9c). Requirements and dependencies preserved from the supplied plan.

## Implementation progress — 2026-10-22

Implementation: `docs/development-agent-pilots.md; dev_agent/operations.py`. Selected three proposed low-risk pilot scopes and documented the exact prospective lifecycle. Implemented authenticated single-count success capture and progress reporting. No real pilot success is claimed; human decisions, deployed observations and seven calendar days remain required.

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
