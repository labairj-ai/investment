# Establish Repository Coding-Agent Contract

- **ID:** 0745
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** none

## Problem

The repository has strong production, investment, CI and canary conventions, but no tool-independent contract governing an autonomous coding agent. A persistent development agent needs explicit authority boundaries before it can discover or implement work.

## Scope and acceptance

- [ ] Add a root `AGENTS.md` defining the coding-agent mission, source-of-record rules, required workflow, authority boundaries and escalation behavior.
- [ ] Preserve the OptiPlex production database as authoritative; development tasks must not write production data, generate production artifacts locally, call brokers or change live trading state.
- [ ] Require plan-before-code for non-trivial work, smallest-scope implementation, focused tests, required regression tests, diff review and evidence before PR readiness.
- [ ] Prohibit direct-to-main implementation by the coding agent, self-approval, test deletion/weakening to obtain PASS, silent baseline rewrites, secret changes and acceptance-threshold reductions.
- [ ] Identify investment-sensitive domains—recommendations, risk policy, position sizing, covered calls, learning/promotion, order/fill generation and account mutation—as elevated-risk work requiring human review.
- [ ] Make the contract model/tool independent so Codex, Claude or another approved runner receives the same repository rules.
- [ ] Document precedence when a TODO, architecture document and agent contract disagree; fail closed and escalate instead of guessing on safety-relevant conflicts.
- [ ] Add a deterministic validation test or script proving required contract sections and forbidden-action language cannot disappear unnoticed.

## QA requirements

- [ ] Existing TODO consistency, release-baseline and CC behavioral-contract gates remain unchanged and pass.
- [ ] Full `pytest tests/ -v --tb=short --junitxml=test-results.xml` passes with no new unexplained skips or waivers.
- [ ] Validate the contract against representative low-risk UI work and high-risk investment-logic work.
- [ ] Record implementation SHA and CI evidence before moving this file to `.todos/done/`.

## Implementation guardrails

- This task establishes governance only; it must not add autonomous execution, deployment or production mutation.
- Do not encode provider credentials, local secrets or machine-specific tokens in the contract.
- Do not weaken any existing investment or release gate to accommodate the agent.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
