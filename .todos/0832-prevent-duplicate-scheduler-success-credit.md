# TODO 0832 — Prevent Duplicate Scheduler Events from Counting as Successful Discovery Runs

- **ID:** 0832
- **Status:** in-progress
- **Priority:** high
- **Risk:** L3 — operational evidence integrity
- **Depends:** 0828 implementation
- **Blocks:** PR #13 merge, 0828 completion, 0831
- **Scope:** Development Agent scheduler/readiness evidence only

## Problem

A manual run can occupy a daily slot before the systemd timer fires. Its later SCHEDULE_DUPLICATE proves timer liveness, not successful systemd discovery. Counting it toward 0828's three runs creates false operational evidence.

## Required behavior and implementation

- [ ] Update dev_agent/scheduler_health.py; preserve duplicate recording.
- [ ] Separate timer_fires, successful_runs, duplicate_runs and failed_runs.
- [ ] Timer duplicates may prove attributable liveness, but never discovery/signal collection success or acceptance-window progress.
- [ ] Success requires event kind SCHEDULE, source systemd-observed-timer, status COLLECTED or BACKLOG_FULL, complete slot/head/timing and no failure for the same invocation.
- [ ] Count distinct America/New_York calendar slots; never count manual/operator retries or multiple systemd retries twice.
- [ ] Preserve stale, disabled, unavailable and 36-hour scheduled-success freshness semantics.
- [ ] Preserve liveness and recent failures in dashboard/readiness and read-only acceptance reporting.

## Required tests and QA

- [ ] Manual COLLECTED plus later systemd DUPLICATE: zero successful runs, one duplicate, observable timer liveness and no acceptance progress.
- [ ] Genuine systemd COLLECTED: one success.
- [ ] Genuine systemd BACKLOG_FULL: execution counts, never implies Builder execution.
- [ ] Multiple duplicates for one slot: zero successes; duplicate attempts deduplicate appropriately.
- [ ] Systemd attempt plus failure: no success, recent failure visible.
- [ ] Manual/operator COLLECTED: no scheduled credit.
- [ ] Multiple genuine retries in one slot: at most one success.
- [ ] Existing scheduler tests and new evidence-integrity tests pass.
- [ ] Dashboard and acceptance report show genuine successful-run counts.
- [ ] No investment/production-state changes.

## Guardrails

Do not loosen the three-run requirement, reinterpret timer liveness as success, manufacture qualifying runs, enable timers, or enable supervised/autonomous execution.

## Done when

- [ ] Duplicates cannot advance 0828 evidence; genuine executions count correctly.
- [ ] Focused/full regression suites and exact-head CI pass.
