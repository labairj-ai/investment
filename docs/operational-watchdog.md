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
