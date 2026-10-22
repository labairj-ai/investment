# Classify Coding-Agent Change Risk

- **ID:** 0761
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0760

## Problem

The development agent needs a deterministic, auditable way to distinguish harmless maintenance from changes that can affect investment decisions, authoritative data or execution behavior.

## Scope and acceptance

- [ ] Define canonical risk levels `L0` through `L5` with explicit semantics: documentation, tests/tooling, read-only UI/analytics, application behavior, investment decision logic, and execution/account mutation.
- [ ] Implement a deterministic classifier over changed paths, semantic manifests and declared TODO scope; model judgment may add risk but must never lower the deterministic floor.
- [ ] Map each risk level to required approvals, test depth, canary requirements, production observation and merge authority.
- [ ] Treat unknown or mixed-scope changes as the highest applicable risk rather than averaging risk downward.
- [ ] Detect attempts to split a high-risk change across multiple low-risk files or commits by evaluating the complete candidate diff.
- [ ] Emit structured classification evidence including reasons, triggering files/rules, final risk level and required gates.
- [ ] Provide an explicit human override path that can raise risk; lowering risk requires recorded rationale and must not bypass mandatory financial/execution controls.

## QA requirements

- [ ] Unit-test each risk level and representative cross-level diffs.
- [ ] Add adversarial tests for renamed files, generated code, indirect imports, policy/config changes and mixed low/high-risk patches.
- [ ] Full suite and existing release gates pass unchanged.
- [ ] Classification is deterministic for the same repository state and diff.

## Implementation guardrails

- Do not let an LLM be the sole authority for risk classification.
- Do not interpret absence of a matching rule as low risk.
- Risk classification itself must not mutate production or development state.

## Numbering history

Renumbered from coding-agent task 0746 to 0761; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/policy.py`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.
