# TODO 0832 — Prevent Duplicate Scheduler Events from Counting as Successful Discovery Runs

- **ID:** 0832
- **Status:** done
- **Priority:** high
- **Risk:** L3 — operational evidence integrity
- **Depends:** 0828 implementation
- **Blocks:** PR #13 merge, 0828 completion, 0831
- **Scope:** Development Agent scheduler/readiness evidence only

## Problem

A manual run can occupy a daily slot before the systemd timer fires. Its later SCHEDULE_DUPLICATE proves timer liveness, not successful systemd discovery. Counting it toward 0828's three runs creates false operational evidence.

## Required behavior and implementation

- [x] Update dev_agent/scheduler_health.py; preserve duplicate recording.
- [x] Separate timer_fires, successful_runs, duplicate_runs and failed_runs.
- [x] Timer duplicates may prove attributable liveness, but never discovery/signal collection success or acceptance-window progress.
- [x] Success requires event kind SCHEDULE, source systemd-observed-timer, status COLLECTED or BACKLOG_FULL, complete slot/head/timing and no failure for the same invocation.
- [x] Count distinct America/New_York calendar slots; never count manual/operator retries or multiple systemd retries twice.
- [x] Preserve stale, disabled, unavailable and 36-hour scheduled-success freshness semantics.
- [x] Preserve liveness and recent failures in dashboard/readiness and read-only acceptance reporting.

## Required tests and QA

- [x] Manual COLLECTED plus later systemd DUPLICATE: zero successful runs, one duplicate, observable timer liveness and no acceptance progress.
- [x] Genuine systemd COLLECTED: one success.
- [x] Genuine systemd BACKLOG_FULL: execution counts, never implies Builder execution.
- [x] Multiple duplicates for one slot: zero successes; duplicate attempts deduplicate appropriately.
- [x] Systemd attempt plus failure: no success, recent failure visible.
- [x] Manual/operator COLLECTED: no scheduled credit.
- [x] Multiple genuine retries in one slot: at most one success.
- [x] Existing scheduler tests and new evidence-integrity tests pass.
- [x] Dashboard and acceptance report show genuine successful-run counts.
- [x] No investment/production-state changes.

## Guardrails

Do not loosen the three-run requirement, reinterpret timer liveness as success, manufacture qualifying runs, enable timers, or enable supervised/autonomous execution.

## Done when

- [x] Duplicates cannot advance 0828 evidence; genuine executions count correctly.
- [x] Focused/full regression suites and exact-head CI pass.

## Implementation and validation evidence

- Implemented on PR #13 from verified starting head `df64c4e5813d1cf2fe675d7358e940d3c2b5e3aa`.
- Validated final application code head: `07875aad350b3b1dad113b74cd029db382bae79b`.
- [Exact-head CI PASS](https://github.com/labairj-ai/investment/actions/runs/40014960716): all eight mandatory gates PASS.
- Focused agent suite: 379 passed. Full suite: 3,078 passed, zero failed, 18 existing skips.
- New scheduler/shared-gate/observer adversarial tests: 84 passed in disposable ledgers. No synthetic evidence was issued as a live certificate or operational success.
- All seven requested policy settings remain unchanged; no financial source, investment state, production data, service or timer was changed.
- Owner promotion is an explicitly unavailable authenticated interface, not a completed issuer; config cannot activate runtime. 0826–0831 remain open for their actual live acceptance.
- PR #13 remains draft, and PR #12 is not merged separately.
