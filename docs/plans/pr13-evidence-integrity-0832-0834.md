# PR13 evidence integrity: 0832–0834

Start: df64c4e5813d1cf2fe675d7358e940d3c2b5e3aa, verified exact PR13 head.
Scope/risk: L5 software evidence and autonomy admission. No financial code, production access, installations or activation.

1. Count timer liveness independently from real scheduled execution. Require a systemd SCHEDULE, accepted status, complete slot/head/timing identity and no same-invocation failure. Deduplicate calendar slots; preserve stale/disabled/unavailable behavior.
2. Extract shared read-only qualification for promotion and runtime: all prior/new operational acceptance, current complete technical/oracle/deployment certification, protection/snapshot freshness, real release and recurrence evidence, scheduler state, window/minima and incident/policy safety. Keep disabled-autonomy preparation outside that primitive. Add an owner-promotion protocol contract and binding validator without an ingestion/authentication implementation; runtime stays denied by default and config cannot grant authority.
3. Cross-bind observer envelope to private transaction and actual deployed head. Validate signed candidate observation and embedded evidence before any success-state mutation. Preserve unhealthy/rollback handling without allowing malformed identity to change candidate state.

Tests: explicit scheduler/manual/duplicate/failure/slot cases; shared blocker parity and read-only checks; owner-promotion unavailable/config-flip/stale-binding cases; signed cross-PR/head/merge/repository/fixture/manual replay with exact state/event invariance; valid progression. Run focused agents, full suite and eight unchanged release gates, push existing branch, wait for exact-head GitHub CI. Keep PR draft, leave 0826–0831 open and all seven specified policy settings unchanged.
