# Create Coding-Agent Pull Requests with Evidence

- **ID:** 0771
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0765, 0769, 0770

## Problem

Once a candidate passes local/reviewer gates, the system needs a consistent PR handoff that gives a human reviewer enough context to decide without reconstructing the agent run.

## Scope and acceptance

- [ ] Implement PR creation for a PR-ready agent branch with canonical title/body format referencing candidate ID and TODO ID.
- [ ] Include problem, scope, risk classification, changed files, acceptance mapping, tests, reviewer result, known limitations, rollback notes and evidence receipt links.
- [ ] Mark PRs draft when any non-blocking evidence is incomplete; do not open a ready-for-review PR when mandatory gates failed.
- [ ] Apply labels or metadata identifying agent-generated changes and risk class when supported.
- [ ] Never enable auto-merge as part of the initial implementation.
- [ ] Detect an existing PR for the same branch/TODO and update evidence instead of opening duplicates.
- [ ] Record PR URL/number in the development ledger.

## QA requirements

- [ ] Mock/API tests verify ready, draft, duplicate and failure behavior.
- [ ] PR body fixtures prove high-risk warnings cannot be omitted.
- [ ] PR creation failure leaves candidate state recoverable and does not mark it merged/deployed.
- [ ] Full suite passes.

## Implementation guardrails

- PR creation is not merge authorization.
- Do not include secret values, raw model prompts containing sensitive data or production DB content in PR bodies.
- Do not push unrelated local commits.

## Numbering history

Renumbered from coding-agent task 0756 to 0771; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/github.py: prepare_pr/GitHub.handoff`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
