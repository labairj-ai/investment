# October 25 Scout incident and bounded recovery proposal

Base: `19fd140227a5b9b3cec27e6a2f91e610842e9947`. TODO 0852 remains
in progress, **0/3**. PR #19 is held and is outside this change. No Scout was
started manually. No production file, service, timer, acceptance or financial
state was changed during diagnosis. This source proposal is not deployment or
acceptance evidence.

## Evidence and limits

[Captured read-only status and journals](live.txt) show the genuine October 25
08:16:47.893213 EDT trigger, failed pre-start PID 1720763 and failed post-stop
PID 1720767. Service InvocationID: `8dba10d6822449aaa99d8bd1dfdfe78c`.
ExecStart has no start timestamp and PID 0. Timer InvocationID:
`cbd67ab35dac4878b0f57abc3353de0b`; timer Result=success, ActiveState=active,
UnitFileState=enabled. LastTriggerUSec is `Sun 2026-10-25 08:16:47 EDT`.
NextElapseUSecRealtime is `Mon 2026-10-26 08:16:45 EDT`.

The actual LastTriggerUSecMonotonic display is:

```
2month 1w 6d 14h 7min 28.893213s
```

The fixed read-only busctl query returns `t 6433648893213`.
Manager-owned service ActivationDetails returns:

```json
{"type":"a(ss)","data":[["trigger_unit","development-scout.timer"],["trigger_timer_realtime_usec","1792930607894325"],["trigger_timer_monotonic_usec","6433648893213"]]}
```

The installed `int(timer['LastTriggerUSecMonotonic'])` cannot consume this live
representation. The exact production string is a regression fixture. This is a
confirmed defect and the first *demonstrably broken* invariant in the recovered
values. It is **not proven to be the first rejection of the historical request**.
The root handler suppressed every exception, and the process/request evidence
needed to establish the earlier checks no longer exists. Do not report a root
traceback or a proven historical parser-stage rejection that was never captured.

The acceptance directory is root:optiplex 0755 and empty. `timer-fires.json` is
absent (does not contain October 25), pending-file inventory is empty, and
`discovery.json` is absent. Therefore the observer never completed the timer-fire
persistence stage. It received and rejected the client request; the furthest
successful internal validation stage is unrecoverable. Root observer journal has
no incident entries. The user journal records a network namespace setup failure
for ExecStopPost and continuation without isolation; that is an independent
reason not to assume every sandbox probe passed. No acceptance credit exists.

## Earlier begin-path checks

| Check | Evidence / limit |
|---|---|
| Request sandbox probes | Historical booleans not retained. Post-stop namespace warning exists. Cannot prove begin passed. |
| ControlPID identity | Historical ExecStartPre PID=1720763; process exited and /proc entry is gone. Current ControlPID=0 is expected, not a historical mismatch. |
| Loaded Scout unit digest | Installed digest matches config/source below; current DropInPaths empty and NeedDaemonReload=no. No historical root check result retained. |
| Loaded sandbox | Current PrivateNetwork=yes, NoNewPrivileges=yes, ProtectSystem=strict, ProtectHome=read-only; effective historical probe result unknown. |
| InvocationID | Exact historical ID survives in service state and PID journal metadata. |
| Client /proc cmdline | Historical process gone; fixed argv survives in ExecStartPre. Cannot prove root read passed. |
| Timer identity | Installed bytes match reviewed timer/config; genuine manager ActivationDetails names it. |
| LastTrigger freshness | Typed trigger=6433648893213; service InactiveExitTimestampMonotonic=6433648908160 (14,947 microseconds later). Old parser cannot reach freshness comparison on formatted text. |
| Boot identity | Happens after broken parser; no evidence it was reached. |
| Source/state snapshot | Happens after timer-fire persistence; no artifact indicates it was reached. Current 1,325 tracked file hashes match trusted old manifest; source head unchanged. |

Installed old identities (SHA-256):

- observer: `8537f44523e434052dfa2379796f43bf85c9c6919ef9e99362c20de682801888`
- root unit: `8254a9471e3219bffca6312ddc6c763fa1ea8ae8a2633a5a3341c8eb4869c9e0`
- Scout service: `e117fd0c25ff2e1d72b6944ff2a9b5ab0753ba71b4c1e53928f2f9f8f5fd7f13`
- Scout timer: `3428a3290345f0dcb0730e21963c390d8168c1aacd22816ab336ce9e2d14db98`

Activation fingerprint: `e061d845506cb4976420ba728ea6fbd26a92eaa3be6a64f6f02d2600916061a1`.
Flags remain SHADOW; autonomous_implementation, supervised_loop_enabled,
supervised_publish_pr and auto_merge are false; required_human_merge is true.
Financial file fingerprints captured read-only (not a historical before/after
bookend and not a claim that ordinary production jobs stop changing databases):

- holdings.csv: `1b05c299a53af4b417587511cfb2be99f823dbe9dd8e562dc8b90cc411e8a882`
- investment.db: `f03c4b723ef236e8eb9f51a8b5e13b863e6d3b6bbd5778b65aabbde9cb3a63d8`
- buffett.db: `cb145b68f3fa6e69946a32aa64d31a3d4526bf211a85d07121f102c3f9013734`

Read-only in-memory control-ledger inspection found 47 SCHEDULER_OBSERVATION rows
and no Scout SCHEDULE/SCHEDULE_ATTEMPT/SCHEDULE_FAILURE records. Database contents
and credentials are not included in diagnostics.

## Correction and provenance

Use fixed `busctl --user get-property` against the exact timer object/interface.
Require the `t` uint64 signature, nonzero bounded value and recent CLOCK_MONOTONIC
age. No duration parser, realtime/monotonic conversion or timestamp fallback.
Require manager-owned ActivationDetails to name the pinned timer and match that
raw trigger; re-read exact InvocationID and ControlPID after querying metadata.
Missing best-effort metadata fails closed. Add RefuseManualStart=yes to the
pinned Scout service. Existing peer/control argv, service/timer digest, loaded
sandbox, boot identity, replay ledger and before/after checks remain mandatory.
The same failed timer event cannot be reused; a distinct genuine recovery event
can begin without manufacturing or resetting a scheduler slot.

D-Bus types are documented in [systemd's interface reference](https://www.freedesktop.org/software/systemd/man/257/org.freedesktop.systemd1.html).
Trigger metadata corroborates typed timer state; it never independently grants
credit. No Builder, worktree, PR, deployment or financial action is added to Scout.

Root journal output is one fixed line per rejection:
`DISCOVERY_OBSERVER_FAILURE <allowlisted reason>`. Explicit trust failures use
stable codes; unexpected exceptions map to BOOKEND_INVALID. Neither exception
text nor request data, paths, file contents, holdings, SQL or credentials are
logged. The actual server response remains exactly `FAILED\n`.

## Reviewed recovery calendar

Keep the existing daily entry and add exactly one absolute entry:

```
OnCalendar=*-*-* 08:15:00 America/New_York
OnCalendar=2026-10-25 10:15:00 America/New_York
```

Persistent=true and RandomizedDelaySec=120 remain. The proposed recovery is
October 25 at 10:15 Eastern plus the reviewed delay. Deployment must finish and
be independently verified before that window. The upgrade refuses a recovery
less than ten minutes away or already elapsed. If review misses the window,
change source and repeat validation/review; never force a service start.
The absolute entry has no later effective firing after October 25. Verify next
future execution is October 26 daily plus delay after observing recovery.

## Separate upgrade and rollback

`python -m ops.discovery.upgrade --root /home/optiplex/investment --head <reviewed-new-merged-main> --expected-old-head 19fd140227a5b9b3cec27e6a2f91e610842e9947`

Default is plan-only. This is intentionally separate from the unchanged
config-only refresh. Only a reviewed operator adds `--apply` after review.
Do not manually copy the observer executable.

The root-only fixed-layout tool requires exact old source/config/executable/root
unit/Scout unit identities, clean main==origin/main and old ancestry. It permits
only the explicitly reviewed observer/Scout service/timer boundary changes; the
root observer unit must be unchanged. It verifies old running runtime/process/
socket, quiescent Scout and a quiet timer window, disabled activation and no
implementation worktree. It refuses nonzero accepted discovery history.

Apply rechecks under a root lock, durably backs up old bytes/modes/owners and all
failure artifacts, verifies observer stop, atomically replaces each fixed file
while stopped, generates exact new config/manifest, reloads only the user manager
because its units changed, verifies Scout identities, starts only the root
observer, and verifies new process/invocation/socket/runtime. It never starts,
stops, restarts or enables Scout or its timer. Financial/activation hashes and
acceptance evidence must remain identical. Failed evidence is preserved without
creating a new receipt; accepted credit remains 0/3 before a real recovery run.

Rollback restores exact old boundary/config files using durable backups, reloads
the changed user units, verifies old Scout identities and leaves the observer
**stopped / NOT READY**: its old config cannot qualify the new source checkout.
No rollback silently rewinds the application checkout or grants acceptance. If
rollback cannot be verified, stop again and return FAILED_*_NOT_READY, preserving
backup material for reviewed recovery. Multi-file installation is transactional
under a stopped observer, with individual atomic renames and verified rollback.

## Required deployment/recovery evidence (not yet performed)

After concrete human review: exact-head CI and eight gates, merge, clean exact
merged-main checkout, plan-only result, explicit apply result, independent
observer/config/units/flags/financial verification, healthy collector/scheduler
observer and all required signal sources. Confirm 0/3 before firing, then leave
the system alone. Observe only the natural timer firing. A successful qualified
run should produce NOT READY, successful_runs=1, required_runs=3,
host_safety_accepted=false and slot scout:2026-10-25. Otherwise preserve the reason
and 0/3; never grant credit manually. PR #19 must later be refreshed/rebased and
fully revalidated against changed main. Do not begin 0853.
