# Enforce Coding-Agent Golden Engineering Principles

- **ID:** 0781
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0760, 0767, 0768, 0780

## Problem

Autonomous agents can amplify existing technical debt and local patterns. The project needs a small set of enforceable engineering principles that guide both generation and review.

## Scope and acceptance

- [ ] Define a versioned set of project-specific golden principles covering single source of truth, deterministic financial arithmetic, explicit unavailable states, immutable evidence, minimal duplication, bounded LLM authority, mobile usability and fail-closed safety.
- [ ] Translate principles that can be machine-checked into deterministic repository checks or tests.
- [ ] Require the Planner/Builder/Reviewer prompts to reference the same principle version.
- [ ] Have the reviewer cite specific principle IDs when requesting changes.
- [ ] Detect principle changes in PRs and require human review rather than allowing the agent to relax its own standards.
- [ ] Support a bounded cleanup candidate type when repeated principle violations are detected.
- [ ] Document exceptions with narrow scope, owner/rationale and expiration/review condition.

## QA requirements

- [ ] Mutation tests prove removal/weakening of required principles is detected.
- [ ] Golden example diffs demonstrate compliant and violating patterns.
- [ ] Full suite passes.

## Implementation guardrails

- Keep the list small enough to be actionable; avoid generic style preferences masquerading as safety rules.
- Agents cannot self-authorize exceptions.
- Principles must not conflict with existing investment-domain contracts.

## Numbering history

Renumbered from coding-agent task 0766 to 0781; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/policy.py: PRINCIPLES; scripts/check_development_agent.py`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
