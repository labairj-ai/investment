# TODO 0839 — Install Read-Only Continuous Discovery

- **ID:** 0839
- **Status:** superseded
- **Priority:** high
- **Risk:** L3
- **Parent:** 0828
- **Depends:** 0835
- **Blocks:** 0841, 0844

## Objective

Activate continuous observation/discovery only. No implementation authority.

## Install

- [ ] Development Scout unit.
- [ ] Scout timer.
- [ ] Scheduler observer unit/timer.
- [ ] Development signal collector unit/timer.

## Preserve

- `supervised_loop_enabled=false`
- `autonomous_implementation=false`
- `supervised_publish_pr=false`
- `auto_merge=false`

## Signal sources

Enable currently reviewed sources:

- GitHub CI failures;
- service health/restarts;
- dashboard HTTP status;
- Development Agent HTTP status;
- TODO/FIXME discovery;
- explicit user feedback.

Do not claim unsupported sources are active.

## Real acceptance

Collect at least three genuine systemd timer slots.

Each qualifying slot must contain:

- systemd invocation identity;
- New York slot;
- exact source SHA;
- start/end;
- duration;
- signal counts;
- discovered count;
- deduplicated count;
- suppression count.

Manual executions and `SCHEDULE_DUPLICATE` do not count.

## Safety

Verify across all runs:

- [ ] no Builder;
- [ ] no worktree implementation;
- [ ] no PR publication;
- [ ] no deployment;
- [ ] no holdings mutation;
- [ ] no investment-state mutation.

## Done when

0828 can close.

## Implementation and acceptance tracking

See [rollout implementation and exact remaining gates](../docs/production-rollout-0835-0844.md) and the [plan](../docs/plans/production-foundation-0835-0844.md). Source preparation is not live operational acceptance. This task remains open until all requirements above have real evidence.


## Superseded

Superseded by TODO 0848 under the simplified solo-owner workflow. Internal safety controls remain, but owner-facing operation is reduced to Go / No-Go. Preserve this file as historical design context.
