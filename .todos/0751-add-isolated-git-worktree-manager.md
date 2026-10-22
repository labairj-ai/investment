# Add Isolated Git Worktree Manager

- **ID:** 0751
- **Status:** backlog
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0745, 0746, 0750

## Problem

Autonomous implementation must not run in the production checkout or contaminate the developer's active working tree. Every task needs an isolated, disposable workspace pinned to an explicit base SHA.

## Scope and acceptance

- [ ] Create a worktree manager that creates one isolated branch/worktree per approved TODO using a canonical branch naming scheme.
- [ ] Record base SHA, branch name, worktree path and TODO ID before the coding agent starts.
- [ ] Refuse to run when the base checkout is dirty in ways that would contaminate the candidate or when the requested base SHA cannot be verified.
- [ ] Prevent concurrent tasks from sharing a worktree, branch or mutable cache that can affect source state.
- [ ] Provide cleanup/recovery for completed, failed and abandoned runs without deleting evidence required by the ledger.
- [ ] Verify generated worktrees cannot point at the OptiPlex production checkout or authoritative production data paths.
- [ ] Support deterministic replay from the recorded base SHA.

## QA requirements

- [ ] Integration tests create, use and clean temporary git repositories/worktrees.
- [ ] Crash/restart tests recover orphaned worktrees safely.
- [ ] Concurrent worktree tests prove path/branch isolation.
- [ ] Full suite passes.

## Implementation guardrails

- Never use `main` as the agent's writable branch.
- Never run `git reset --hard`, clean or destructive commands against an unverified path.
- Do not store credentials inside worktrees.

## Source

Created from the 2026-10-21 design for a governed continuous-improvement coding agent for the Investment Dashboard.
