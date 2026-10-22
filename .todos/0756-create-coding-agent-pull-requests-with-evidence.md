# Create Coding-Agent Pull Requests with Evidence

- **ID:** 0756
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0750, 0754, 0755

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

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
