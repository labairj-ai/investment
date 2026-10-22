# TODO 0808 — Disable Git Hooks and Ambient Git Configuration for Agent Git Operations

- **ID:** 0808
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** medium
- **Depends:** 0751, 0771
- **Blocks:** 0801

## Problem

The coding model itself has no process authority, but trusted orchestration invokes host Git commands including commit and push.

Git hooks and ambient Git configuration can execute host processes indirectly during those operations.

The Development Agent should not depend on the host having benign Git hooks.

## Scope and acceptance

- [ ] Create a canonical Development Agent Git execution wrapper.
- [ ] Disable repository/global hook execution for agent Git operations.
- [ ] Use an isolated Git configuration environment where practical.
- [ ] Explicitly set `core.hooksPath` to a non-executable/empty location.
- [ ] Ensure commit operations cannot invoke pre-commit, prepare-commit-msg, commit-msg or post-commit hooks.
- [ ] Ensure push operations cannot invoke pre-push hooks.
- [ ] Preserve required Git identity configuration without inheriting unrelated global settings.
- [ ] Audit existing direct `subprocess.run(["git", ...])` calls in `dev_agent/`.
- [ ] Route sensitive Git mutations through the hardened wrapper.
- [ ] Record exact Git command intent in evidence without leaking credentials.

## QA requirements

- [ ] Malicious pre-commit hook does not execute.
- [ ] Malicious pre-push hook does not execute.
- [ ] Global hook path cannot override agent configuration.
- [ ] Normal worktree creation/commit/push still functions.
- [ ] Candidate cannot configure hooks through writable scope.
- [ ] Git remote remains restricted to the expected repository.

## Implementation guardrails

- Do not disable normal human Git hooks globally.
- Hardening applies only to Development Agent-controlled operations.

## Source

User-supplied 2026-10-22 trust-boundary code-review follow-up. Backlog creation does not authorize implementation, promotion, pilot execution or autonomy activation.

## Implementation checkpoint — 2026-10-22

Implementation is on `codex/trust-boundary-0803-0809`; see the
[implementation plan](../docs/plans/development-agent-trust-boundaries-0803-0809.md)
and [trust-boundary contract](../docs/development-agent-trust-boundaries.md).
Source/fixture validation does not close environmental acceptance. This TODO remains
open pending its complete QA, required human decisions and exact-head CI evidence.
