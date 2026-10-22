# Build Bounded Coding-Agent Runner

- **ID:** 0767
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0760, 0761, 0765, 0766

## Problem

The project needs a controlled execution harness for Codex/Claude-style coding runs rather than an unrestricted shell loop.

## Scope and acceptance

- [ ] Implement a provider-neutral runner contract that accepts one approved TODO, pinned worktree, allowed tools, time/step budget, repository contract and validation commands.
- [ ] Start with one provider implementation while keeping provider-specific prompt/transport logic behind an adapter.
- [ ] Provide only the minimum repository context needed for the task and always include `AGENTS.md`, TODO acceptance criteria and relevant guardrails.
- [ ] Enforce command allow/deny policy, workspace confinement, maximum iterations, maximum diff size and explicit timeout/termination states.
- [ ] Capture structured run output: provider/model identity, prompt contract version, commands/actions summary, changed files, test results, stop reason and evidence references.
- [ ] Stop and mark `NEEDS_HUMAN` on forbidden operations, repeated failures, ambiguous safety conditions, scope expansion or budget exhaustion.
- [ ] Do not allow the runner to merge, deploy, modify secrets, call brokers or write authoritative production data.

## QA requirements

- [ ] Use fake provider/runner fixtures for deterministic unit and failure-path tests.
- [ ] Integration tests prove workspace confinement and blocked forbidden commands.
- [ ] Model/runner failure cannot leave a task falsely marked successful.
- [ ] Full suite passes.

## Implementation guardrails

- Initial runner operates only on human-approved TODOs.
- No unrestricted `--dangerously-skip-permissions` style mode in scheduled operation.
- Provider credentials must come from existing secret/config mechanisms and never be logged.

## Numbering history

Renumbered from coding-agent task 0752 to 0767; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/providers.py; dev_agent/runner.py`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
