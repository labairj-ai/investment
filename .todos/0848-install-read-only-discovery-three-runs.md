# TODO 0848 — Install Read-Only Discovery and Prove Three Real Runs

- **ID:** 0848
- **Status:** in-progress
- **Priority:** high
- **Risk:** L3
- **Depends:** deployed PR #14 foundation
- **Blocks:** 0849
- **Supersedes:** 0839

## Objective

Enable only read-only Development Agent discovery. It may identify work but may not modify code.

## Install

- [x] Scout service and timer.
- [x] Scheduler observer.
- [x] Signal collector.

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

## PR #14 source progress (simplified workflow)

One exact-head owner Go is the authority for merge and downstream deployment;
No-Go/stale-head and all technical gates remain fail-closed. No service is installed,
no live owner decision is created, and all activation flags remain disabled.
See `docs/solo-owner-governance.md` for the active workflow. Source tests are not
live acceptance. This TODO remains open until all its acceptance evidence exists.


## Evidence review — 2026-11-09: operational acceptance satisfied; UI criterion open

Current-source acceptance is **3/3**, advanced from 2/3 on November 9 at source
`6db0b6ccf2494721d024a6e29ecf8fbb55c66bf6`. Genuine slots November 7/8/9 match
root-owned authenticated closing receipts; no manual/fixture/historical-source credit.
Scout, daily timer, scheduler observer, signal collector and private state are installed.
All required identity, slot, SHA, timing, signal, candidate, duplicate/suppression
and result fields are retained. Ledger/investment/Buffett integrity checks returned
ok with no foreign-key violations; host receipts prove no Builder, worktree,
source, PR, deployment, holdings or financial-state violations. All four listed
activation flags remain false. Source/CI safeguards for idempotency, bounded retries,
backlog, freshness and unavailable required signals remain enforced. Existing
source-transition/merge/deployment evidence and current receipt are indexed in
[the evidence review](../docs/evidence/development-todo-review-20261109/README.md).

- [x] Three distinct genuine current-source runs and host safety acceptance.
- [ ] Owner-facing **Discovery: READY** result. Certification API reports 3/3
  but its status still inherits NOT READY from the incomplete scheduler inventory
  (existing 1,000-record bound). This is a presentation/aggregate gap, not missing
  genuine-run credit. Do not relax that bound or manufacture scheduler evidence.

Keep this TODO in-progress solely for that original owner-facing criterion.
No additional natural run, source reset or production deployment is needed to
prove the existing 3/3. Resolving the projection belongs to separately authorized
work; this housekeeping change does not implement it. This acceptance does not
complete supervised, autonomy, physical-device or overall certification work.
