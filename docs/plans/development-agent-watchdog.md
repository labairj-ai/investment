# Development discovery watchdog implementation plan

Base: 19fd140227a5b9b3cec27e6a2f91e610842e9947. TODO0855, WD-DA-001–012.
Owner subsequently authorized building/testing the source now for deferred deployment.
Do not touch OptiPlex, merge/deploy, change activation, invoke Scout/Builder, or alter
acceptance. Existing 0852 continues on the pinned source.

Read-only host adapter -> pure classification -> existing watchdog persist/deliver
and existing dashboard. Adapter permits only fixed systemd/Git read queries and
read-only bounded source/ledger/spool/root-evidence reads. No producer APIs.
Acceptance projects existing scheduler_health.acceptance only. Genuine success
also needs matching protected root per-invocation evidence; manual/forged ledger
rows cannot clear missing-run incidents. Observations persist only in watchdog.db.

Schedule uses America/New_York, reviewed random delay/accuracy/completion window,
first real scheduler observation as installation boundary, bounded configurable
lateness grace/escalation, and existing signal/scheduler freshness ceilings. No
retrospective first-run incident and no acceptance credit for monitoring.

The runner always checks discovery independently of investment DB/baseline health.
Existing incidents/notification retry and dashboard API remain the only framework.
Actual supervised admission reads fresh independent source-bound watchdog coverage
and active watchdog timer before any worktree/Builder side effect. A reviewed
activation source may permit the existing supervised loop; discovery-phase control
drift remains immediately RED. No flags are enabled by this change.

Tests: pure classification matrix, Eastern/DST and time boundaries, partial
acceptance progression, root permission/symlink/invocation/unsafe proof, source and
control drift, fresh/stale/failed sources, existing incident/alert integration,
read-only snapshots/no authority interfaces, real admission denials before side
effects, dashboard controls absent. Preserve existing tests/skips/baselines. Run
focused/full and all eight gates at exact head and real GitHub CI. Open review PR;
no merge/deploy. Deployment still requires completed 0852 plus separately reviewed
post-acceptance observer/source transition; zero-run refresh cannot bypass history.
