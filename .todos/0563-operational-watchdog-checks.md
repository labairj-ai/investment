# Add Deterministic Operational Watchdog Checks

- **ID:** 0563
- **Status:** done
- **Created:** 2026-09-21
- **Priority:** high
- **Depends:** none

## Problem

Independent scheduled pipelines can silently stop before creating run records. Existing macro-health monitoring detects some stale scoring failures but does not prove experiment collection, labeling, MTM and backups continue completing successfully.

## Proposed approach

- Extend or consolidate the existing scripts/macro_health_watchdog.py and macro-health-watchdog timer rather than introduce duplicate operational truth. Run independently of serve.py every 15 minutes, with schedule-aware hourly/daily checks.
- Aggregate existing authoritative ledgers for serve/DB availability, holding scoring, candidate scoring and certification, Opportunity Hunter, experiment capture, labeling, learning sweeps, virtual-book MTM, source freshness and backups. Record expected/start/success timestamps, source record ID, cadence, status, detail and checked_at in system_watchdog_state.
- Derive expectations from actual enabled schedules, ET timezone, DST, trading sessions/holidays, grace windows and deployment start boundaries. Distinguish never-started, failed, stuck, successful, legitimately skipped and not-yet-due work. A process, timer or flag file is not proof of success.
- RED: DB unavailable, unexpected accepted-contract/protocol change, unusable acceptance, nonzero production macro influence/nonzero stage, explicit failure or stale STARTED work. YELLOW: missed completion deadline, overdue work, declining coverage or approaching staleness. No divergence and insufficient mature evidence are informational.
- Pin expected acceptance/scorer/protocol identities in an explicit deployment baseline separate from experiment state. Never auto-adopt observed drift; approved operational baseline updates must not rewrite experiment history. Certification freshness follows existing contract policy, not an invented time-to-live.
- Use an append-only watchdog_events transition log with linked detection/resolution events; derive resolved_at in a view/state projection rather than mutate an append-only event. Persist minimal fallback evidence outside SQLite when the DB itself is unavailable.
- Add missing completion instrumentation only where existing records cannot prove success. In particular, serve.py currently logs backup subprocess failure without propagating it: a recent backup flag must not count as successful durable backup. Establish a successful consistent SQLite snapshot and destination completion receipt, including legitimate unchanged backups.
- Alert-only: no restarts, rescoring, retries of business jobs, data repair, certification, recommendation changes, promotion, or experiment-state mutation. Watchdog may write only its own state/events and narrowly scoped producer completion receipts. Do not change frozen scorer/protocol hash inputs.

## Touches

scripts/macro_health_watchdog.py; systemd/; agent_db.py; serve.py; backup_data.sh; tests/; operational documentation.

## Done when

- [x] Each component has a documented authoritative success source, expected cadence, grace window and severity policy.
- [x] Deterministic clock/DB fixtures cover never-started, stuck, failed, healthy, not-due, holiday/DST and missing-DB cases without live external calls.
- [x] State and immutable incident transitions survive repeated runs; DB failure remains externally observable.
- [x] Backup health requires verified successful snapshot/destination completion, not a scheduler flag or attempt.
- [x] Independent timer and checks preserve accepted scorer, experiment epoch and stage-0 production behavior.
- [x] QA evaluation conducted: functionality verified working, no regressions introduced.

## Completion — 2026-09-21

Implemented and deployed on Optiplex. The independent timer and alert-only service pass live checks; the accepted experiment epoch, collection clock and stage-zero influence remain unchanged. See [operational verification](../docs/operational-watchdog.md#verified-deployment--2026-09-21). Full local regression: 1,376 passed, 16 skipped; implementation CI passed. Transport failure/deduplication tests used fake senders; no synthetic emails were sent.
