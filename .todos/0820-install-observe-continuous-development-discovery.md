# TODO 0820 — Install and Observe Continuous Development Discovery

- **ID:** 0820
- **Status:** in-progress
- **Priority:** high
- **Risk:** L3 — operational scheduler
- **Depends:** 0816, 0817
- **Blocks:** 0821, 0822, 0824

## Problem

The repository includes a bounded `development-scout.timer`, but readiness currently reports:

`installation=UNAVAILABLE: scheduler installation is not observed`

The architecture therefore supports scheduled discovery but cannot prove that discovery is actually running.

## Scope and acceptance

- [ ] Install `development-scout.service` and `development-scout.timer` using the reviewed operator deployment workflow.
- [ ] Preserve read-only discovery behavior.
- [ ] Preserve `PrivateNetwork=true`.
- [ ] Preserve `NoNewPrivileges=true`.
- [ ] Preserve restricted writable paths.
- [ ] Keep implementation/build invocation out of the scout timer.
- [ ] Record scheduler installation state.
- [ ] Record enabled/disabled state.
- [ ] Record next scheduled run.
- [ ] Record last attempted run.
- [ ] Record last successful run.
- [ ] Record run duration.
- [ ] Record discovered candidate count.
- [ ] Record deduplicated candidate count.
- [ ] Record suppressed candidate count.
- [ ] Record failure reason when applicable.
- [ ] Expose scheduler health on `/development-agent`.
- [ ] Mark scheduler stale if no successful run occurs within an agreed threshold.
- [ ] Make `readiness.py` consume observed scheduler evidence rather than hard-coded UNAVAILABLE.
- [ ] Ensure a scout failure never launches implementation.
- [ ] Ensure retry remains bounded.
- [ ] Ensure `Persistent=true` behavior does not create duplicate candidate records.

## Required tests

- [ ] Timer installed but disabled reports DISABLED.
- [ ] Timer enabled reports healthy schedule.
- [ ] Successful scout updates last-success timestamp.
- [ ] Failed scout reports failure without creating implementation activity.
- [ ] Duplicate daily run is idempotent.
- [ ] Backlog cap is honored.
- [ ] Candidate cap is honored.
- [ ] Private-network restriction is preserved.
- [ ] Scheduler cannot invoke build/autonomous-cycle.

## QA requirements

- [ ] Observe at least three actual scheduled scout executions.
- [ ] Confirm systemd timer times are correct across America/New_York timezone.
- [ ] Verify dashboard state matches `systemctl` state.
- [ ] Verify no production investment state changes across scout runs.

## Implementation guardrails

- This task authorizes discovery scheduling only.
- Do not enable autonomous implementation.
- Do not schedule Builder.
- Do not schedule deployment.
- Do not grant network access to the discovery service unless separately reviewed.

## Done when

- [ ] Scheduler is installed and healthy.
- [ ] Dashboard reports actual scheduler status.
- [ ] Three scheduled discovery runs have durable receipts.
