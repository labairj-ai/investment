# TODO 0852 — Enable Read-Only Discovery and Prove Three Scheduled Runs

- **ID:** 0852
- **Status:** in-progress
- **Priority:** high
- **Risk:** L3
- **Parent:** 0848
- **Depends:** merged PR #14 source foundation
- **Blocks:** 0853

## Objective

Install and enable only the read-only Development Agent discovery path and prove it can safely identify real improvement opportunities.

No implementation authority is granted.

## Install

- [ ] Scout service/unit.
- [ ] Scout timer.
- [ ] Scheduler observer.
- [ ] Development signal collector.
- [ ] Private state/log locations with reviewed permissions.

## Allowed signals

Use only currently reviewed sources:

- GitHub CI failures;
- application/service health;
- dashboard/API health;
- source TODO/FIXME discovery;
- explicit owner/user development signals.

Do not invent synthetic production signals merely to satisfy acceptance.

## Three-run acceptance

Observe at least three distinct genuine timer-triggered runs.

Each qualifying run must preserve:

- [ ] systemd/launch scheduler invocation identity;
- [ ] America/New_York schedule slot;
- [ ] exact source SHA;
- [ ] start/end/duration;
- [ ] signal counts;
- [ ] discovered candidates;
- [ ] deduplicated/suppressed counts;
- [ ] final result.

Manual runs do not count.

Duplicate scheduler events do not count as additional successful runs.

## Safety acceptance

Across all three runs verify:

- [ ] no Builder invocation;
- [ ] no implementation worktree;
- [ ] no source mutation;
- [ ] no PR creation/publication;
- [ ] no deployment;
- [ ] no investment database mutation;
- [ ] no holdings mutation;
- [ ] no financial/execution action.

## Owner-facing result

Expose only:

Discovery: READY

or

Discovery: NOT READY — <reason>

## Guardrails

Keep:

- supervised_loop_enabled=false
- autonomous_implementation=false
- supervised_publish_pr=false
- auto_merge=false

Do not turn discovery findings into implementation automatically in this TODO.

## QA

Confirm scheduler idempotency, duplicate-run rejection, freshness handling, bounded backlog and fail-closed behavior when required signal sources are unavailable.

## Done when

Three real scheduled discovery runs are accepted with zero authority or investment-state violations and 0848 can be closed.

## PR #15 source progress

Read-only bootstrap, dedicated GitHub reader transport, complete signal counts and exact-source scheduled-run acceptance are implemented. Acceptance requires three distinct real slots plus protected host safety observations; source fixtures cannot qualify. Installation and all three genuine runs remain outstanding.

No live acceptance is claimed. All operational checkboxes remain open. See
[the rollout guide](../docs/development-agent-pr15-rollout.md) for internal prerequisites.
