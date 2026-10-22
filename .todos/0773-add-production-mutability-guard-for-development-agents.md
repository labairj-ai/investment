# Add Production-Mutability Guard for Development Agents

- **ID:** 0773
- **Status:** in-progress
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0760, 0761, 0766, 0767

## Problem

The coding agent must be technically prevented—not merely instructed—from modifying authoritative investment state or production services during development runs.

## Scope and acceptance

- [ ] Build a guard that denies writes to known production DB paths, production output directories, service configs, deployment commands and broker/network endpoints from the development runner.
- [ ] Resolve paths canonically before policy evaluation to prevent symlink, relative-path or alternate-mount bypasses.
- [ ] Separate read-only production evidence access from mutation authority; snapshots used for tests must be copied or opened read-only.
- [ ] Block shell/process patterns capable of indirect production mutation unless a separately authorized deployment workflow is active.
- [ ] Log denied operations with candidate/TODO/run identity but redact secrets.
- [ ] Restore guard state reliably after exceptions and across repeated runs.
- [ ] Provide an explicit test-only sandbox fixture for mutation attempts.

## QA requirements

- [ ] Adversarial tests cover symlinks, `..`, alternate paths, subprocesses, SQLite URI modes, shell redirection and helper scripts.
- [ ] Prove representative production tables/files remain byte/row-identical during canary runs.
- [ ] Full suite passes.

## Implementation guardrails

- Instruction text is not a substitute for technical enforcement.
- Unknown production-like paths or commands fail closed when running autonomously.
- Deployment authorization is out of scope for this task.

## Numbering history

Renumbered from coding-agent task 0758 to 0773; the original ID collided with another task sequence. Historical SHA/PR links remain unchanged.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.

## Implementation progress — 2026-10-21

Implementation: `dev_agent/guard.py; dev_agent/runner.py: ContainerValidator`. See [harness implementation](../docs/plans/development-agent-harness.md) and [operator contract](../docs/development-agent.md).

Local fixture/adversarial coverage is in `tests/test_development_agent.py`; the checked-in browser script covers exact mobile/desktop widths. Final branch CI and human review are required before task completion. Original acceptance checkboxes remain the independent acceptance checklist rather than an automatic claim of completion.

External gate: Docker is unavailable on the development host and OptiPlex. OS validation confinement remains UNAVAILABLE until a preprovisioned digest-pinned image/runtime is independently exercised.
