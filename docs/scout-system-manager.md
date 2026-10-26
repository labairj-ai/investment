# Reviewed system-manager Scout migration (not applied)

Production remains PR22 `43d4fda5d7c032290d51574a6d2f283d09127ee4`.
Both October 25 failures remain zero credit. Acceptance is NOT READY, 0/3;
no discovery.json, SCHEDULE, candidates or accepted slots were manufactured.
The PR22 observer backup and journals are preserved. PR19 remains held/unmerged;
0853 is blocked. This PR is source and fixture evidence, not host certification.

## Read-only host diagnosis

OptiPlex reports systemd 255.4-1ubuntu8.18, Linux 6.8.0-137-generic x86_64.
`kernel.unprivileged_userns_clone=1`, `user.max_user_namespaces=62950`, and
`kernel.apparmor_restrict_unprivileged_userns=0`. None was changed. PID1 has
effective capabilities including CAP_SYS_ADMIN; the optiplex user manager has
CapEff=0. The loaded user Scout reports PrivateNetwork=yes, PrivateUsers=no.
The actual stop-post journal reports network namespace setup EPERM and execution
continuing without isolation. Thus the existing per-user configuration demonstrably
failed; enabled userns sysctls alone do not establish a working sandbox. No active
namespace experiment or manual Scout was performed. PID1 runtime capability will
be tested by a separate certification before any future migration enables Scout.

Retained InvocationID `bf947a2e20fa46699bcf00001e678453` command records have
D-Bus type `a(sasbttttuii)`, binary `/usr/bin/python3`, argv
`/usr/bin/python3 -I -S /opt/investment-discovery-observer/observer.py <mode>`:

| Command/mode | PID | Start realtime us | Start monotonic us | Finish realtime us | Finish monotonic us | code/status |
|---|---:|---:|---:|---:|---:|---|
| ExecStartPre / begin | 1818840 | 1792976447909252 | 6479488908139 | 1792976447972750 | 6479488971637 | 1/1 |
| ExecStart / scout | 0 | 0 | 0 | 0 | 0 | 0/0 (never ran) |
| ExecStopPost / end | 1818846 | 1792976447983228 | 6479488982116 | 1792976448040464 | 6479489039352 | 1/1 |

The first reason was SCOUT_CONTROL_PROCESS_INVALID; retained evidence cannot
identify its exact old subcheck. Do not reinterpret it as a proven PID mismatch
or timer-parser failure. End reported SANDBOX_PROBE_FAILED with the explicit
namespace warning. Native timer/ActivationDetails matched: monotonic
6479488893913, realtime1792976447895021. The manager's invocation-entry monotonic
was6479488908167, 28us after the Pre command start; the new guard accounts for
this bounded v255 state-transition ordering without accepting completed records.

Primary implementation references:
[systemd v255 namespace semantics](https://github.com/systemd/systemd/blob/v255/man/systemd.exec.xml),
[v255 timer activation](https://github.com/systemd/systemd/blob/v255/src/core/timer.c).
No claim is made that all possible user-namespace configurations are unsupported;
this change avoids depending on them and changes no kernel/security settings.

## Provenance and diagnostics

Only Scout moves to `/etc/systemd/system/development-scout.service` and `.timer`.
It runs as User=optiplex/Group=optiplex, never root. WorkingDirectory and paths are
fixed absolute OptiPlex paths. The reviewed sandbox, credential/financial denial,
private network/tmp, strict source mounts, bounded control write path and
RefuseManualStart=yes remain. Collector/scheduler-observer stay user units.

Observer queries use the system manager, with no --user/XDG_RUNTIME_DIR. Begin
binds the socket's SO_PEERCRED PID to the manager's active ExecStartPre record;
end uses ExecStopPost. A single exact executable/argv, ignore-errors=false,
positive start clocks, no finish/exit yet, correct active phase, current
InvocationID and invocation-entry bounds are required; the row is re-read to
reject races. An aggregate ControlPID of zero cannot override a valid per-command
record; a conflicting nonzero PID fails. Completed/missing/wrong/stale rows fail.
No caller PID/argv or environment trigger claim is authoritative.

Stable diagnostics add SCOUT_CONTROL_PID_MISMATCH, SCOUT_FRAGMENT_MISMATCH,
SCOUT_DROP_IN_UNEXPECTED, SCOUT_RELOAD_REQUIRED, SCOUT_UNIT_DIGEST_MISMATCH,
SCOUT_ARGV_MISMATCH, SCOUT_EXECUTION_RECORD_INVALID and SCOUT_MANAGER_QUERY_FAILED.
Only allowlisted codes enter root diagnostics. No actual argv/path/request/data
is logged. The socket client still receives only FAILED on failure.

Timer origin retains typed uint64, <=180s freshness, exact pinned system units,
RefuseManualStart, TriggeredBy, current invocation, boot identity, manager-owned
ActivationDetails and replay ledger. Scout's own trigger uses system MainPID=self,
INVOCATION_ID, typed fresh timestamp and matching ActivationDetails, then rechecks
invocation/MainPID. Unavailable manager proof yields untrusted operator origin,
never trusted timer origin. Fixed filesystem AF_UNIX system-bus access is tested
inside the cert sandbox; no caller-env fallback or weaker bridge is installed.
Scheduler health labels Scout system scope and both companion timers user scope.

The target timer has only daily10:00 America/New_York, Persistent=true,
RandomizedDelaySec=120 and Unit=development-scout.service. No absolute October25
entry remains in the timer. Earlier recovery documentation is historical only.

## Dedicated transaction and rollback

Use the reviewed isolated influence launcher with --migrate-scout, exact target
merged-main --head and --expected-old-head43d4fda...; default is PLAN_ONLY. This is
not bootstrap or config-only refresh. The legacy user bootstrap explicitly refuses
the new system-Scout templates before mutation. Future source deployment must occur first.
It requires root/fixed layout, isolated system Python, clean tracked exact merged
main/origin, ancestry, full manifest, influence PASS, exact old observer/root unit/
user Scout digests, installed ledger/spool, quiescent Scout, old timer active,
zero accepted history/no discovery.json, disabled SHADOW/L2 flags, no Builder or
implementation worktree. No blanket untracked absence condition is introduced.

Apply takes an exclusive root lock and rechecks the plan; durably backs up old
observer/config/user units plus existing failure evidence; stops/disables the old
user timer and verifies quiescence; stops observer; atomically installs only the
reviewed observer/config/system Scout and cert files; system daemon-reloads;
checks system unit identity; executes the separate certification; verifies ledger
prefix/schema and protected state; only then enables/starts the new system TIMER,
never Scout service; checks next normal Eastern slot and no Scout invocation;
restarts/verifies observer process/socket/runtime; verifies exact installed bytes,
both manager states, unchanged source/financial/activation and zero acceptance.
There is never an intentional state with both Scout timers active.

The new system timer must have no existing system persistent stamp or loaded
system-unit history/configuration. No stamp is edited/deleted/copied or fabricated.
First activation is authorized only before **09:50:00 America/New_York on the
current local date**. At or after the cutoff it fails closed, including after
10:00; authorization never rolls to tomorrow. This guard runs in inspect, again
under the lock immediately before boundary mutation, and after certification
immediately before timer enable. Crossing the cutoff during certification uses
the stopped/not-ready rollback. Native next-elapse must be today’s 10:00–10:02
Eastern interval, never tomorrow or an immediate/past trigger. Persistent=true
is retained; no catch-up behavior is relied upon to authorize activation. Existing system
history or any elapsed recovery entry fails closed, never reset to force a pass.

Failure stops/disables both timers, stops observer and restores verified old
bytes/metadata; new reviewed files are removed. Financial DBs and ledger are never
restored. Any PID1-created runtime stamp is preserved, never cleaned. Restored old
observer pins old source while checkout remains new, so it stays STOPPED/NOT READY.
Rollback verification failure also leaves stopped/not-ready with durable result;
no automatic retry. The retained old user unit files remain disabled on success.

## Test-only runtime certification

`development-scout-sandbox-certification.service` is separate from Scout. PID1
runs each Pre/Main/Post as optiplex using the same relevant sandbox, with additional
ledger/acceptance denial. The fixed installed isolated Python script imports only
stdlib, performs no application imports, SQL, writes, candidate/schedule/bookend
calls or acceptance access. It emits fixed booleans only: runtime routes/interfaces
and IPv6 loopback isolation, source mount read-only, protected/credential denial,
expected UID, system manager readable and its own active per-command record.
All three phases must pass and belong to a fresh cert invocation. A configured
PrivateNetwork property or successful main phase alone is insufficient. Reports
explicitly say test_evidence_only=true/accepted_scout_run=false and are never
written into discovery acceptance. Fixture PASS is not real host certification;
the reviewed migration must execute this cert on the host before enabling Scout.

No production migration, real host certification, sysctl/security change or manual
Scout is performed by this PR preparation. No 0853 work or PR19 change.
