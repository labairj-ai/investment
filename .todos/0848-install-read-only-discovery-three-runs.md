# TODO 0848 — Install Read-Only Discovery and Prove Three Real Runs

- **ID:** 0848
- **Status:** backlog
- **Priority:** high
- **Risk:** L3
- **Depends:** deployed PR #14 foundation
- **Blocks:** 0849
- **Supersedes:** 0839

## Objective

Enable only read-only Development Agent discovery. It may identify work but may not modify code.

## Install

- [ ] Scout service and timer.
- [ ] Scheduler observer.
- [ ] Signal collector.

## Initial signals

Use reviewed sources only: GitHub CI failures, service health, HTTP health, source TODO/FIXME discovery and explicit owner/user development signals.

## Acceptance

Observe at least three genuine timer-driven discovery runs. Manual runs and scheduler duplicates do not count.

Preserve invocation identity, source SHA, New York slot, start/end, duration, signals found, deduplication, candidates generated and result.

## Safety verification

Across all three runs confirm no Builder invocation, implementation worktree, PR creation, deployment, financial-state mutation or holdings mutation.

## Owner-facing result

After acceptance, dashboard shows Discovery: READY.

## Guardrails

Keep supervised_loop_enabled=false, autonomous_implementation=false, supervised_publish_pr=false and auto_merge=false.

## Done when

The system has safely discovered real improvement opportunities on its own.
