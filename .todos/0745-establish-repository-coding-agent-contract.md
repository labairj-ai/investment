# Establish Repository Coding-Agent Contract

- **ID:** 0745
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** none

## Problem

The repository has strong production, investment, CI and canary conventions, but no tool-independent contract governing an autonomous coding agent. A persistent development agent needs explicit authority boundaries before it can discover or implement work.

## Scope and acceptance

- [x] Add a root `AGENTS.md` defining the coding-agent mission, source-of-record rules, required workflow, authority boundaries and escalation behavior.
- [x] Preserve the OptiPlex production database as authoritative; development tasks must not write production data, generate production artifacts locally, call brokers or change live trading state.
- [x] Require plan-before-code for non-trivial work, smallest-scope implementation, focused tests, required regression tests, diff review and evidence before PR readiness.
- [x] Prohibit direct-to-main implementation by the coding agent, self-approval, test deletion/weakening to obtain PASS, silent baseline rewrites, secret changes and acceptance-threshold reductions.
- [x] Identify investment-sensitive domains—recommendations, risk policy, position sizing, covered calls, learning/promotion, order/fill generation and account mutation—as elevated-risk work requiring human review.
- [x] Make the contract model/tool independent so Codex, Claude or another approved runner receives the same repository rules.
- [x] Document precedence when a TODO, architecture document and agent contract disagree; fail closed and escalate instead of guessing on safety-relevant conflicts.
- [x] Add a deterministic validation test or script proving required contract sections and forbidden-action language cannot disappear unnoticed.

## QA requirements

- [ ] Existing TODO consistency, release-baseline and CC behavioral-contract gates remain unchanged and pass.
- [ ] Full `pytest tests/ -v --tb=short --junitxml=test-results.xml` passes with no new unexplained skips or waivers.
- [x] Validate the contract against representative low-risk UI work and high-risk investment-logic work.
- [ ] Record implementation SHA and CI evidence before moving this file to `.todos/done/`.

## Implementation guardrails

- This task establishes governance only; it must not add autonomous execution, deployment or production mutation.
- Do not encode provider credentials, local secrets or machine-specific tokens in the contract.
- Do not weaken any existing investment or release gate to accommodate the agent.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation evidence and unresolved gate

Implementation: `93389c050deb7a4f8b6ac3cc7c64aa58bbe9d381`, based on
`ac6642c02070524ac27e15b19c062147359c9c4c`. Draft PR:
https://github.com/labairj-ai/investment/pull/2

Root `AGENTS.md` applies to every approved provider and preserves production
authority, financial-domain human review, PR workflow and fail-closed precedence.
`check_agent_contract.py` is a read-only presence/language guard, not a semantic
proof or runtime confinement mechanism. Forty-four focused tests pass, including
removal/weakening, hidden clauses, duplicate sections and low/high-risk examples.
The CI workflow adds this check without altering existing gates.

Existing CC behavioral-contract validation fails identically in the candidate and
a disposable detached worktree at untouched base SHA, using Python 3.12.12:
baseline engine `fccf8fce066e0dc5…`, observed `3b05de06097d6126…`; simulator
`36094c7261e2f313…` matches. No component version bump or applicable manifest is
present. Python 3.9 reproduced the same mismatch; changing interpreter did not
resolve it. No financial source, baseline, manifest or acceptance threshold was
modified by this task.

Fail closed: do not move this TODO to done, mark the PR ready, merge, or start
dependent TODOs until the existing gate conflict is resolved through its required
reviewed financial change-control procedure. Human review is required for this
contract and any resolution affecting financial semantics.

### Local regression result

Python 3.12.12 full prescribed suite: **2,635 passed, 7 failed, 18 skipped**.
JUnit: local `test-results.xml`; console log:
`/private/tmp/investment-0745-clean-tests.log`. The unchanged release-baseline
inventory rejects all seven failures; no waiver was added. Failures are two CC
velocity tests, CC inventory CLI, two CC event-authority CLI tests, and two
portfolio-brief eligibility tests. The velocity/news failures reproduce on untouched
base; the CLI failures report the existing engine fingerprint mismatch.
All 44 new contract tests pass. The temporary Python 3.9 environment was moved
outside the checkout before the final run so static source guards scan only
repository code and the conventionally excluded `venv/` environment.

Real GitHub CI for implementation SHA:
https://github.com/labairj-ai/investment/actions/runs/39698833027
The TODO and contract steps passed; final CI status is tracked in the PR.
No TODO completion or PR readiness is claimed.

All seven failing test nodes also reproduce in targeted runs on untouched base.
The 18 existing conditional skips comprise 15 broker-credential integration tests
and 3 generated-dashboard/Node checks; no skip markers or waivers were added.
Machine-readable local inventory:
`docs/evidence/coding-agent-0745-local-20261021.json`.
