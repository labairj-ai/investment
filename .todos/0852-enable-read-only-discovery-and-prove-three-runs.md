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

### PR #15 operational usability follow-up

The protected automatic observation daemon and authenticated before/after Scout hooks now generate measured host-safety evidence. Installation primes and validates the read-only signal spool before enabling any timer. The producer cannot invent timer events; three genuine observed runs remain outstanding.

## Actual host progress — 2026-10-24

The reviewed root observer is installed outside application source, active and
read-only over investment/source state. The reviewed discovery installer failed
closed at `dedicated read-only GitHub credential unavailable`, before writing
user units, priming a spool or enabling timers. The backup/owner credential was
not reused. Scout, collector and scheduler observer remain uninstalled/disabled.

Genuine discovery: **0/3**. No timer invocation, generated candidate or automatic
bookend observation exists. No discovery.json was manufactured. The next actual
timer cannot be reported until installation/priming succeeds. The reviewed
calendar remains 08:15 America/New_York with up to 120 seconds random delay.

See [live evidence](../docs/evidence/l0-live-20261024/README.md). Holdings, both
investment databases, the control ledger and activation flags remained unchanged.
Discovery: NOT READY — dedicated read-only GitHub credential unavailable.

### Explicit public reader source support

An explicit unauthenticated public mode is proposed separately from the dedicated
private-token mode. Only reviewed GitHub metadata/workflow HTTPS GETs are reachable;
canonical public visibility is reverified on every collection, credentials and gh
are never consulted, and rate-limit/privacy failures invalidate the old spool and
stop Scout before candidate discovery. Private mode retains independent read-only
permission verification. No mode is installed/activated by source tests, and no
real timer acceptance or implementation authority is granted. See the rollout guide.


### Observer pin transition source follow-up

PR17 merged at `88f1757af1ed090983ce262a1936a41dbf8a279b` without deployment.
The installed root observer and live checkout remain at `05d6cccf734d4604d1a8c10406d9e3d7598e9c6f`.
A separate source PR adds a plan-only-by-default, config-only trust-pin refresh
for the pre-discovery zero-run state. It requires unchanged observer/Scout boundary
Git objects, exact clean target main, protected installed identities and verified
rollback; it cannot migrate acceptance or install/enable user discovery units.
Neither this change nor PR17 has been applied on OptiPlex. Genuine runs remain
**0/3**. Both the historical failed token installation and explicit public-reader
source support above remain separate facts. See the rollout guide for boundaries.


### October 25 timer failure / reviewed recovery proposal

The genuine 08:16 EDT timer attempt failed in ExecStartPre; ExecStart did not run.
Acceptance remains **0/3**. The installed parser cannot consume systemd's actual
formatted LastTriggerUSecMonotonic value; root exception suppression prevents
proving whether an earlier historical check rejected first. No failed attempt is
converted to credit. See [incident evidence and proposed recovery](../docs/evidence/scout-oct25/README.md).
A separate source proposal adds typed timer provenance, sanitized diagnostics,
a bounded exact-boundary upgrade and one October 25 12:15 Eastern recovery entry.
These are source changes pending review, merge and deployment; no operational
checkbox is complete and PR #19 remains held. Any genuine recovery must qualify
against the new exact merged source and retain all three-run safety requirements.
