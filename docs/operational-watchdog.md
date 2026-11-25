# Operational watchdog

The operational watchdog extends the existing macro-health runner. It executes
independently of `serve.py` every 15 minutes, reads the production investment DB
with SQLite `mode=ro`, and writes only its own `out/watchdog.db` projections,
incident transitions, producer receipts and delivery attempts. It never restarts
services, retries business jobs, repairs labels, scores candidates, changes
acceptance, promotes models or changes recommendations.

## What counts as success

| Component | Authoritative evidence and expectation |
| --- | --- |
| Service / database | Bounded HTTP heartbeat plus read-only DB query every check |
| Acceptance / protocol / influence | Explicit deployment baseline pins active acceptance, scorer, validation config, protocol, base contract, epoch and production routing source hashes; stage-zero policy must match |
| Holding scorer | Complete full-refresh run, matching item completion, expected/scored counts and zero failures; Saturday 01:00 ET, six-hour grace |
| Candidate scorer / preparation | Separate candidate ledger plus whole preparation completion receipt; weekdays 04:00 ET, six-hour grace |
| Certification / runtime evidence | Existing provenance gate across latest decision-relevant envelope; common dimensions and certification coverage, with no invented certification TTL |
| Agent pipeline | Successful trigger evaluation / agent completion receipt; Saturday 07:00 ET, six-hour grace, plus any actual triggered runs |
| Opportunity Hunter | Authoritative agent run and independent sweep expectations recorded before experiment capture; no invented daily unconditional OH schedule |
| Experiment | Each completed OH run after watchdog activation has an observed cohort or explicit exclusion; five-minute completion grace |
| Learning | Models applicable at sweep entry must have completed learning sweep rows linked by agent run ID |
| Outcome labeling | Weekday 18:00 ET process receipt (one-hour grace), plus valid due 5/21/63-session labels for all current-epoch candidate episodes and paired cohort labels |
| Virtual-book MTM | Weekday 18:30 ET process receipt (one-hour grace), plus complete daily marks for applicable books on every due market session since activation/inception |
| Freshness | Existing score warning thresholds and runtime evidence policy, latest portfolio price session, due outcome/MTM evidence |
| Backup | Successful consistent SQLite snapshot, integrity check, Git push and verified destination HEAD; daily 20:00 ET backstop with one-hour grace; an earlier successful same-day backup satisfies it |

Schedules use America/New_York and preserve DST behavior. Market-dependent due
work uses the repository NYSE calendar, including holidays; unsupported calendar
years are an explicit failure. Process receipts prove command completion, while
separate completeness checks catch labeler/MTM commands that exit successfully
without producing all due records. Empty/no-candidate sweeps have explicit
operational exclusions. No divergent picks and no mature outcomes are normal.

The watchdog activation boundary prevents retrospectively demanding new receipts
from old runs. It does not reset the macro experiment or its collection clock.
Existing current-epoch outcomes are still checked when they mature. Failed
prospective captures are reported, never backfilled. Exclusions exceeding half of
at least five monitored sweeps warrant investigation; this is an operational
threshold, not a statistical promotion gate.

## State and incidents

`system_watchdog_state` is the latest component projection with expected/start/
success timestamps, source ID, cadence, severity and check time. `watchdog_events`
is an append-only OPEN / SEVERITY_CHANGED / RESOLVED transition log; resolution
is represented by a new linked event rather than editing an old event.
`watchdog_receipts` and immutable `watchdog_sweeps` provide only the missing
producer completion/expectation evidence. Source investment ledgers remain the
business truth.

RED covers explicit failures, stale started work, missing cohort/learning lineage,
contract drift and unavailable DB/service. YELLOW covers missed completion windows,
incomplete due outcomes/marks, source freshness and coverage deterioration.
Uninspected components retain old evidence and become stale rather than being
silently cleared. The dashboard cannot report HEALTHY after 35 minutes without a
check. `out/watchdog_latest.json` and `out/watchdog_failure.json` provide fallback
evidence outside SQLite; systemd/journal exposes watchdog execution failure.

## Alerts

`--notify` enables actual operational incident alerts using the same configured
`EMAIL_FROM`, `EMAIL_APP_PASSWORD` and `EMAIL_TO` transport as the application.
No credentials or portfolio evidence payloads are emailed. RED incident openings
or escalations notify immediately; unresolved YELLOWs appear in one digest after
20:00 ET. INFO has no notification. There are no periodic RED reminders or recovery
emails in v1. Failed notification delivery retries at 15m, 30m, 1h, 2h and at most
six-hour intervals; it never retries investment jobs. Transport tests use fakes.
A crash after SMTP accepts a message but before delivery acknowledgement can cause
a duplicate on retry; SMTP does not offer an exactly-once transaction with SQLite.

When the watchdog's own SQLite storage fails, a JSON-throttled fallback alert and
journal error remain available. An on-host watchdog cannot alert during complete
host/network failure; external monitoring is outside v1.

## Deployment and inspection

On Optiplex, after deploying the reviewed code, initialize the baseline once:

```sh
venv/bin/python scripts/macro_health_watchdog.py --initialize-baseline
venv/bin/python scripts/macro_health_watchdog.py
```

Initialization refuses to overwrite an existing baseline and requires current
acceptance, an existing epoch and stage zero. The second command checks real
records and renders proposed alerts without sending them. Only after reviewing
that output install the supplied service/timer units, including the receipt
wrappers on candidate preparation, outcome labeling and MTM. Restart the web
service to activate pipeline receipts and the read-only dashboard API. Enable
`macro-health-watchdog.timer`; its service invokes `--notify` for actual incidents.
No synthetic test alerts need to be sent.

An explicitly reviewed future deployment can archive the old baseline and create
a new one. Do not run initialization automatically during ordinary refreshes or
use it to accept unexpected source drift. Rebaseline only operational expectations;
never rewrite an experiment epoch to silence monitoring.

```sh
systemctl status macro-health-watchdog.timer macro-health-watchdog.service
journalctl -u macro-health-watchdog.service --since today
curl -fsS http://127.0.0.1:5001/api/watchdog
cat out/watchdog_latest.json
```

Learning Lab displays a compact read-only System Watchdog card. There are no
remediation controls. A watchdog RED exit makes the oneshot service failed while
the independent timer remains active and continues checking for recovery.

## Verified deployment — 2026-09-21

The initial read-only dry run found no pipeline/contract failures; its only warning
was the intentionally not-yet-started watchdog timer. After activation, the live
service returned HEALTHY across 34 checks, with systemd Result=success and exit 0.
The independent timer is active on the 15-minute schedule. Existing outcome/MTM
and candidate preparation units now use completion receipt wrappers.

A real deployment-verification backup completed successfully, including destination
HEAD verification at `f51815d2d784de6744e23a8373a029c5301394b2`, with receipt
`427d0457-880f-48b1-a662-f13683509145`. The unchanged-data path also pushes any
previously unpushed commit before declaring destination success.

The Learning Lab API and generated card were checked. Native browser visual
inspection was unavailable because macOS computer-use permissions were pending;
no visual inspection is claimed. The compact card exposes key checks first and
collapses additional healthy checks and timing. Warnings remain immediately visible.

The macro experiment remains at epoch
`83b0f50ce2e40ef5922a1718e0527cbe44e2957964eaf12f8a8481327da1e75a`,
collection start `1789995200.4390466`, stage 0, with three observed cohorts at
verification time. No historical experiment data was rewritten. Watchdog continuity
counts explicitly start at watchdog activation and display the epoch's total
observed count separately.

Full local regression: 1,376 passed, 16 skipped. Implementation CI run
[35628293623](https://github.com/labairj-ai/investment/actions/runs/35628293623)
passed. Live notification attempts were zero because no alertable incident was
present; error/retry/deduplication paths were tested with fake transport.


## Development Discovery (prepared source; not deployed)

TODO0855 adds Development Discovery to this same runner, incident log, delivery
policy, API and dashboard. It does not add another daemon/alert framework. Source
preparation was authorized while 0852 runs on pinned main19fd140; merge/deployment
must wait for its three genuine accepted slots and the separately reviewed
post-acceptance observer/source transition. Do not use the zero-run pin-refresh
tool after real history exists, erase history or move old-head credit to new code.
New-source qualification remains mandatory wherever current admission requires it.

`discovery_watchdog_reader` allows only fixed read-only Git/systemd queries and
bounded protected file reads. Git optional locks/hooks/ambient configuration are
disabled. The ledger is inspected as a query-only in-memory SQLite snapshot;
active journals/WAL or unstable reads fail closed rather than being repaired.
It never imports a producer adapter or receives a ledger writer, Builder, GitHub
write, worktree or deployment interface. The classifier is pure data -> checks.
Only the existing watchdog persists its own projections/incidents/delivery state.

Sources are the actual timer/service metadata, exact clean deployed Git source,
protected root observer config/manifest and installed executable/unit, active
observer service and private socket metadata (no socket/API call), private signal
spool, real discovery
ledger and protected root per-run bookends. The existing acceptance calculation
is projected unchanged. A manual/forged/synthetic ledger success cannot clear a
missing-run incident without its matching root-owned real invocation/slot proof.
Absence of root evidence before any completed real run is PENDING, not an alarm.
At0/1/2 runs healthy progression is ACCEPTING; READY requires the authoritative
three-run result including aggregate host safety. Watchdog health grants no credit.

Scheduling uses timezone-aware America/New_York dates, including DST and genuine
persistent catch-up. Reviewed delay120s + timer accuracy60s + observer completion
240s bound the normal completion window; `config/development_watchdog.json` adds
900s grace before YELLOW and7200s missed-run escalation to RED. Invalid thresholds
are RED; no existing freshness ceiling can expand. The spool remains valid at most
36hours, with delayed hourly collection warned after4500s; scheduler observations
warn after1800s and expire at the existing3600s. Distinct failed collector/observer
invocations are remembered only in watchdog's own projection for repeated-failure
classification, never retried by the monitor.

The protected source-pin timestamp plus first real scheduler observation anchor
current-source scheduling obligations. Historical ledger rows remain untouched;
pre-transition rows do not masquerade as current-source operational runs. The
existing acceptance calculation still receives the complete snapshot and filters
source itself. Cached origin/main is read/reported without fetching: a newer
cached ref alone does not replace an intentionally pinned deployed source. HEAD,
its full trusted manifest and observer pin must still match; unreviewed drift RED.
Existing bounded acceptance inventories remain fail-closed if exhausted; monitoring
does not prune or expand them. A legitimate transition must preserve/archive old
root proof through its separately reviewed mechanism, never through watchdog code.

During discovery-only phase all four implementation/publication/merge flags remain
false, SHADOW/L2/human merge required; unexpected Builder processes, implementation
state/worktrees or PR/merge/deployment events are immediately RED. A future normal
reviewed activation source may enable the existing supervised loop only when its
configuration is committed, clean and bound by the protected observer manifest.
The component derives that phase from this reviewed configuration, not a request
flag, model response, new owner ceremony or monitoring exception. Autonomous
implementation and auto-merge remain forbidden. No controls change in this PR.

0853's actual entry checks, manual CLI worktree/build/publication routes and
low-level supervised start authorization require fresh complete independent watchdog projections
for the same source/code identity, genuine watchdog producer InvocationID/MainPID,
active pinned existing watchdog timer, fresh actual inspection timestamp and
no unresolved RED (including incident-history consistency), authoritative3/3/host
safety and the reviewed supervised controls. Failure blocks before worktree/Builder;
coverage is rechecked before subsequent Builder/publish steps. The consumer reads
only the fixed production watchdog.db, never a candidate-checkout projection. Dashboard readiness
uses the same admission. No serialized HEALTHY flag can authorize implementation.

The dashboard shows status/acceptance/source/last-next Scout/signals/host safety and
observed Builder state, with diagnostic expansion only. No Run/Retry/Repair/Enable/
Reset control exists. Alerts contain fixed reason codes and typed component/slot/
source/last-success metadata, never raw ledger/spool/portfolio/credential payloads.
All existing notification deduplication, YELLOW digest and delivery retries remain.

Live acceptance is still outstanding: after0852 and the reviewed transition, allow
the existing watchdog timer to perform a genuine independent inspection, verify
its component projections and dashboard, and prove admission stays blocked until
all current-source requirements hold. No test fixture is production evidence and
no synthetic incident or Scout run should be created for rollout verification.

The observer service/source/unit/socket can fail RED before the first scheduled
Scout, without calling its producer API. A completed ledger row whose actual
systemd service is still bookending remains pending only inside the reviewed
240-second window; it cannot clear an overdue incident until root proof exists.
A later genuine root-bookended success can resolve an earlier failed attempt.

Discovery subchecks retain per-component incidents. The aggregate dashboard row
does not duplicate an equal/worse child notification; aggregate-only inspection
failures still alert. Existing delivery keys, retry intervals and YELLOW digest
behavior are reused unchanged for all pre-existing components.

### October 30 source refresh: deployment remains blocked

Scout is a SYSTEM service/timer at 16:00 America/New_York (120s randomized delay).
Collector and scheduler observer remain USER units. This observational PR neither
repairs timer provenance nor starts Scout, changes scheduling, installs its own
observer, or grants acceptance. A failed Pre with no SCHEDULE remains RED even if
Unit.ActivationDetails still describes a prior success. Current Job provenance is
validated by the separately reviewed Scout repair, never inferred by this display.

A protected acceptance_epoch must equal the exact deployed head. Its receipt is
read only from the corresponding root-owned epochs/<head>/discovery.json; the old
receipt is historical evidence and never a fallback for new-source credit. Missing
new receipt means pending qualification; malformed/cross-source selection fails
closed. A separately authorized transactional source transition must permanently
archive the old 1/3 evidence and establish the new 0/3 epoch before deployment.
PR #19 stays separate from that transition, cannot be deployed under a Scout GO,
and requires its own exact-head owner approval plus later qualification/rollout
review. TODO 0853 remains blocked; no remediation or implementation authority.
