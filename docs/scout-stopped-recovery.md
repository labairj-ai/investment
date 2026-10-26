# Stopped Scout migration recovery and 16:00 Eastern qualification

PR24 starts from application/main a8f0a9a9f1932a18383e33c212061204713b233c.
The restored observer boundary remains43d4fda5d7c032290d51574a6d2f283d09127ee4,
stopped; the exact old user Scout timer is disabled. No system Scout boundary or
persistent stamp exists. This is STOPPED_ROLLBACK, not a bootstrap conflict.
All prior failures and the separate certification remain zero accepted runs.
PR19 remains held/unmerged;0853 is blocked.

## Historical facts and limits

Retained PR23 evidence: /etc/investment-discovery-observer/
scout-system-migration-backup-a8f0a9a9f1932a18383e33c212061204713b233c;
operator review and three reports in /private/tmp/pr23-retry/.

| Event | October26 Eastern evidence timestamp | Meaning |
|---|---|---|
| APPLY process start |09:14:06.799890|durable runner start|
| Backup manifest creation |09:14:40.609005923|filesystem birth/mtime|
| Old user timer stop |09:14:40.815899|user-manager journal|
| Old observer stop completion |09:14:40.840375|system-manager journal|
| System boundary installation |not retained precisely|ordered before certification by reviewed code|
| Certification start |09:14:41.345453|manager journal|
| Certification Pre report |09:14:41.415385|PID1898575|
| Certification Main report |09:14:41.499009|PID1898585|
| Certification Post report |09:14:41.583737|PID1898596|
| Certification command completion |09:14:41.589697|manager journal|
| Rollback start |not retained precisely|no progress receipt existed|
| Rollback result creation |09:14:42.511982769|filesystem birth/mtime|

Certification InvocationID bc0fb3603cd447078928603705bc43c8. All three reports
proved runtime isolation/denial/UID/system-manager/own command-record booleans,
and explicitly test_evidence_only=true, accepted_scout_run=false. There is no
system timer start in the retained journal. No precise historical failing
invariant is proven. Do not turn the missing evidence into a guessed ledger,
state, timer, clock, stamp or certification defect.

The ledger contains scheduler observations only; acceptance directory is empty,
0/3, no accepted slots, no discovery.json/SCHEDULE/candidates. Holdings and both
DB logical identities matched across rollback. Source-deployment receipt remains
DEPLOYED_VERIFIED independently of the failed boundary migration.

## Two exact starting modes

NORMAL_ACTIVE retains the existing live observer process/socket/runtime checks
and exact active/enabled user timer. STOPPED_ROLLBACK requires exact old canonical
config/source/root unit, root-controlled runtime, inactive/dead observer with PID0,
no socket and no observer process, exact old user units with inactive/disabled
timer, quiescent Scout, no system/certification units or live processes, zero
accepted history and disabled implementation flags. Mixed states fail closed.

Stopped recovery never starts the old observer or enables the old timer. The
transaction verifies their stopped state, installs only reviewed new boundary
files and runs certification anew. New observer start occurs only after the new
system timer has been validated. Rollback restores exact old bytes/metadata and
keeps both Scout timers and observer stopped/NOT READY. It never restores DBs or
ledger history or deletes persistent history.

## Durable progress and failure reporting

Every real APPLY backup contains root-owned0600 progress.json, schema
scout-system-migration-progress-1. Atomic replacement fsyncs the complete new file
and backup directory. A bounded append-only logical stage inventory contains only
attempt UUID, exact old/target SHAs, start mode, allowlisted stage/result/code and
start/completion timestamps. No raw exceptions, argv/environment, credentials,
SQL, holdings or DB contents. No caller payload becomes a diagnostic.

Stages cover preflight, backup, old quiescence/timer/observer, installation/reload/
identity, certification started/passed, separate ledger/acceptance/protected-state
checks, old timer state, activation window, timer enable/state/next-elapse, observer
start/final boundary, completion and rollback start/completion. The certification
PASSED stage is written only after the complete existing corroboration returns.

Every failed result includes failure_stage/failure_code. Ledger, acceptance,
protected state, old timer, cutoff, stamp, system enable/state, next-elapse,
observer start/boundary, system boundary and certification failures have distinct
stable codes. Unknown failures are UNCLASSIFIED_MIGRATION_FAILURE. Failed rollback
returns ROLLBACK_FAILED and retains original stage/code separately. Preflight
rejection does not create a backup or mutate the installed boundary.

## Daily 16:00 Eastern contract

Exactly one calendar: OnCalendar=*-*-* 16:00:00 America/New_York.
Persistent=true, RandomizedDelaySec=120, Unit=development-scout.service remain.
No10:00/08:15/absolute recovery entry. Keep 16:00 Eastern throughout3/3 qualification.

First activation requires today's time strictly before15:50:00 Eastern. Inspect,
under-lock, pre-old-transition and post-certification checks enforce the same
current-date slot. No rollover authorization. First native next-elapse must be
TODAY16:00–16:02 inclusive. Old10:00, past, tomorrow, early or late values fail.
No persistent stamp is created/copied/edited/reset by migration code.

System Scout still runs User=optiplex/Group=optiplex with RefuseManualStart,
PrivateNetwork runtime probes, strict/read-only mounts, no-new-privileges and exact
credential/financial denial. Per-command records, typed timer, ActivationDetails,
tracked Git source authority and acceptance rules remain unchanged. Certification
is test-only and cannot grant acceptance. No Builder/PR/merge/deploy/financial
execution authority is added to Scout. Three genuine root-bookended daily slots
are still required; no failed attempt receives credit.


## PR26 stable qualification schedule

From base b94e6d4a2203329f9654d71d7161479ce1afe8b2, the owner explicitly
moves daily qualification to 16:00 America/New_York, with a strict same-day
15:50 cutoff and today's 16:00–16:02 next-elapse interval. Keep this schedule
through all three genuine daily runs. The system timer runs independently;
no manual Scout invocation or user reminder is required. No one-time calendar
or persistent history manipulation is permitted. PR25's lifecycle-independent
launcher cache and every stopped-recovery, certification and acceptance
contract remain unchanged. 0852 remains at zero until real accepted runs;
PR19 remains held and 0853 blocked.
