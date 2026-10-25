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
OnCalendar=2026-10-25 18:30:00 America/New_York
```

Persistent=true and RandomizedDelaySec=120 remain. The proposed recovery is
October 25 at 18:30 Eastern plus the reviewed delay. Deployment must finish and
be independently verified before that window. The upgrade refuses a recovery
less than ten minutes away or already elapsed. If review misses the window,
change source and repeat validation/review; never force a service start.
The absolute entry has no later effective firing after October 25. Verify next
future execution is October 26 daily plus delay after observing recovery.

## Separate upgrade and rollback

`/usr/bin/python3 -I -S ops/discovery/influence.py --root /home/optiplex/investment --head <reviewed-new-merged-main> --upgrade --expected-old-head 19fd140227a5b9b3cec27e6a2f91e610842e9947`

Default is plan-only. This is intentionally separate from the unchanged
config-only refresh. Only a reviewed operator adds `--apply` after review.
Do not manually copy the observer executable.

The root-only fixed-layout tool requires exact old source/config/executable/root
unit/Scout unit identities, tracked-clean main==origin/main and old ancestry. It permits
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

After concrete human review: exact-head CI and eight gates, merge, tracked-clean exact
merged-main checkout, plan-only result, explicit apply result, independent
observer/config/units/flags/financial verification, healthy collector/scheduler
observer and all required signal sources. Confirm 0/3 before firing, then leave
the system alone. Observe only the natural timer firing. A successful qualified
run should produce NOT READY, successful_runs=1, required_runs=3,
host_safety_accepted=false and slot scout:2026-10-25. Otherwise preserve the reason
and 0/3; never grant credit manually. PR #19 must later be refreshed/rebased and
fully revalidated against changed main. Do not begin 0853.


## Earlier conservative influence proposal (superseded below)

The all-untracked-empty prerequisite was incompatible with the established
OptiPlex layout. It has been replaced, not bypassed: require empty
`git status --porcelain --untracked-files=no`, branch main, exact HEAD/origin/main,
old ancestry and exact reviewed tracked manifest. Production runtime/data files
remain in place. The previous 9,367-item metadata inventory and zero-move manifest
remain unchanged at `/private/tmp/scout-recovery-current/` on the review workstation.
No file is deleted/quarantined or hidden with excludes.

`ops/discovery/influence.py` is a bounded standard-library-only standalone audit.
It inspects **all** Git-untracked paths, including ignored files, so `.gitignore`
cannot conceal an attack. Bounds: 100,000 paths, 24 MB path listings, 16 MB reviewed
Python source and 250,000 Git metadata nodes. It emits only path/reason/count and
reviewed-module metadata, never credentials, financial contents or raw requests.
It examines Git metadata/config before running hardened Git commands, rejecting
active hooks, executable config overrides, alternate objects, replacement refs,
grafts, attributes overrides and symlinked Git interpretation paths.

The closed import graph is computed with AST from exact reviewed Git blobs, seeded
by ops.discovery.upgrade, ops.discovery.observer and dev_agent.cli, including
relative imports and package initializers. All reviewed Python/executable package
roots plus dev_agent/ops/scripts/config/systemd/.github are protected, including
namespace packages. Untracked extensions inside those namespaces, root modules/
packages/native code, execution configuration, collisions, unresolved parents and
symlinks into tracked source or fixed observer/config/Scout unit paths fail closed.
Unknown root/nested configuration fails closed. Reachable dynamic import machinery
requires explicit new review; it is not inferred safe from extension or filename.

State directories are derived from reviewed observer data paths; virtual environment
roots are identified by actual pyvenv.cfg layout with no tracked source beneath.
Their files are **non-authoritative**: they cannot supply Python code to the fixed
observer/Scout/upgrade interpreter. Root data/document/backup files may remain only
when they do not match reviewed import/configuration names or executable shapes.
Validated CACHEDIR.TAG tool caches are outside tracked/import namespaces, and cannot
disguise executable code. A virtual-environment marker cannot authorize a root
package initializer. Excluded runtime paths do not become trusted source.

Audit-only uses system Python `-I -S`, before any repository package import. The
standalone launcher audits first and only then imports the fixed upgrade module;
apply additionally requires the fixed system interpreter and protected cache
ancestry. Direct ambient `python -m` is not a safe entrypoint: untracked package
initializers or site hooks could run before an in-module guard. The isolated
launcher above invokes the same plan/apply implementation without that bootstrap
gap. This remains plan-only unless `--apply` is explicit.

Scout also sets a protected pycache prefix before importing repository code, and
disables bytecode writes. Thus existing checkout __pycache__ files are runtime
data, never executable authority; `.pth`, sitecustomize, usercustomize and venv
site-packages are not loaded under system Python -I -S. Sourceless `.pyc`, native
extensions and package/module additions in trusted namespaces remain rejected.
The upgrade repeats the influence audit under lock and after applying. Existing
loaded Scout digest/drop-in properties remain separately verified.

A second instance of the same formatted-duration bug was found in
`dev_agent.scheduler.trigger()`. It now uses the same fixed typed uint64 query,
nonzero/range/freshness requirements and existing exact MainPID/InvocationID check.
Root timer provenance and before/after acceptance remain independently mandatory.
Without this correction a genuine run could pass begin but be labelled operator
and fail the existing end-bookend acceptance. No acceptance rule was loosened.

Before merge the actual host must pass this new audit against the candidate's
reviewed module graph. If any current source/configuration path still fails, stop
for ChatGPT review without automatically loosening the classification. Tests cover
allowed databases/backups/caches/large venv inventories, namespace and root-module
shadowing, native/extensionless execution, package initializers, symlinks, ignored
attacks, Git hooks/config/object interpretation, unit/drop-in attacks, and dirty
tracked source despite a passing untracked audit.

## Tracked-source discovery authority (supersedes filename-only exclusions)

Review found that both architecture_signals and daily scoring used unrestricted
protected_graph(root), so untracked files could alter architecture proposals,
cycles, duplicates and candidate risk. Tracked TODO names also used working-tree
bytes, TODO context used filesystem globs, and scheduler policy used working-tree
JSON. The former source label therefore overstated the actual authority boundary.

`dev_agent.reviewed_source.reviewed_sources(root, head)` now obtains its canonical
inventory from exact Git ls-tree objects and source/context bytes from regular
blobs. It uses the existing hardened Git execution contract with replacement
objects disabled. It requires a full lowercase 40-character current HEAD, regular
blob modes, unique canonical paths, bounded tree/file/byte counts and matching
blob object hashes. It never opens a source working-tree path or follows an
untracked source symlink. The immutable view includes reviewed Python, TODO
Markdown, development configuration, all tracked path names and a source-view
identity. A changing HEAD fails closed. Limits: 10,000 files, 4 MB tree listing,
2 MB per source file and 16 MB aggregate selected source.

Scout TODO/FIXME bytes, architecture graph, repeated exception/debt analysis,
duplicate-function bodies, cycle detection, active/completed TODO context,
architecture exclusions and scheduler risk graph use that same view. Recent
commit context is pinned to that head. The scheduler reads policy/caps from its
reviewed configuration rather than an untracked or dirty working-tree file.
Externally supplied signals remain explicit runtime inputs, never implicit source.

| Input | Authority |
|---|---|
| Python analysis, TODO/FIXME markers, dependency graph, duplicate/exception/debt/cycle analysis | Exact reviewed Git blobs |
| .todos/*.md and .todos/done/*.md context, exclusions and discovery configuration | Exact reviewed Git blobs |
| Recent history and repository path inventory | Exact reviewed Git head/objects |
| Operational signal spool, explicit signals, Development Agent ledger | Runtime evidence; existing validation and bounds unchanged |
| Before/after financial/source hashes, systemd process/timer identities, worktree inventory, discovery.json | Root observer evidence; existing trust/acceptance unchanged |

protected_graph(root) itself is unchanged. Planning, whole-diff and worktree
classification retain conservative filesystem coverage. Live discovery invokes
its existing sources= argument through the reviewed view, never its unrestricted
rglob mode. Runtime ledger/spool handling and all acceptance thresholds are unchanged.

The influence audit now distinguishes actual import and execution resolution
from filenames alone. Import shadows use Python's source/bytecode/native loader
suffixes and package identity, not arbitrary data stems. token.json/csv/txt/md/bak
cannot shadow token just by name; token.py, applicable token.pyc/native modules and
token/__init__.py remain rejected. Package initializers, site hooks, native code,
reachable package/module additions, explicit unit execution, configuration/Git/unit
changes and ambiguous dynamic execution still fail closed.

After the tracked-source contract is established in reviewed source, legacy Python
outside the reachable production import roots can remain non-authoritative when
it is neither imported, consumed by reviewed source nor executed by reviewed or
installed units. No individual legacy-file whitelist is used. Non-code data and
inert backups below package directories are evaluated by these same influence
conditions. Merely having an executable mode does not make an unreferenced .bak a
Python import; an actual unit/script reference still rejects it. Runtime directories
cannot conceal a unit execution target. The audit includes the collector entrypoint
and inspects bounded reviewed/installed service/drop-in command references without
emitting command or environment contents. Ambiguous shell/model-tool execution
requires review. Policy labels themselves are distinguished from file-content reads.

The only developer-metadata category is a regular, nonsymlinked, non-executable
.claude/settings.local.json, provided production source/units do not consume it.
There is no .claude/** exemption. Interactive Claude Code settings do not configure
system Python -I -S, the root observer, Scout, public-reader collector, scheduler
observer, systemd or the isolated upgrade launcher. The file is never read or
promoted to trusted source by this classification. Other .claude paths fail closed.

New tests inject untracked agents/evil.py, orchestrator.py, tests and TODOs and
prove identical Scout proposals/context, reviewed graph, risk, score, candidate
identity/files/evidence. Committing Git blob changes changes analysis. Dirty
working-tree source cannot replace reviewed bytes and still fails root observer/
upgrade verification. A separate conservative graph test proves an untracked
import bridge still increases worktree classification risk. Existing tests that
intend authoritative architecture source now commit their fixtures explicitly.

The real inventory will be re-audited only against the final exact candidate head.
If any path still fails, stop for ChatGPT review without a post-result exception.
This task stops before merge even if the proposed new boundary passes. Production
remains at 19fd140... and 0852 stays 0/3 until a later reviewed deployment and real
bookended timer executions; no acceptance is manufactured by source tests.

## Exact-path and usage-aware references (current reference contract)

The bare-literal model is removed. A filename in a forbidden tuple, diagnostic,
label or basename comparison is POLICY_LITERAL_ONLY: it creates no filesystem
reference and does not participate in path disposition. There is no basename or
stem authority match and no exemption for the three previously rejected names.

The bounded AST analysis resolves repository-relative path constructions, aliases,
constant joins, bounded literal loops and helper parameters. It preserves complete
path context: ROOT/'out/investment.db' refers only to out/investment.db. It cannot
create a root investment.db reference. Calls and source lines are retained in the
review evidence. No analyzed Python or production file content is evaluated.

References have two consuming effects:

- SOURCE_OR_EXECUTION_AUTHORITY: content/config reads, database decision inputs,
  import/load/execute targets, and data-derived values passed into those mechanisms.
  Any such use dominates evidence uses of the same exact path and rejects an
  untracked supplier, including files below otherwise permitted runtime locations.
- PROTECTED_RUNTIME_EVIDENCE: metadata, sandbox denial predicates and structurally
  verified read-only hash/logical-hash helpers. Helper names alone grant no privilege.
  Digest helpers cannot parse/execute configuration, write files or have unknown
  calls; database hashes require read-only URI/query-only/dump-to-digest behavior;
  denial helpers must return booleans and use only read-only open/close. A hash result
  used to choose configuration or an executable propagates authority back to its input.

Evidence is allowed only with reviewed sandbox proof: strict/read-only repository
mount policy, no writable repository carve-out, denied probe paths actually listed
as inaccessible, no import/execution/source/config use, and no content observation
of a path that the root observer itself must be denied. Existing loaded-unit/pin
verification remains independently mandatory before an upgrade. The model does not
run probes, open a credential or read financial data to prove these properties.

Dynamic rooted paths and unresolved source/config path constructors fail closed.
Parameter effects propagate through reviewed helpers; bounded analysis that cannot
converge fails closed. Fixed discovery CLI modes derive from reviewed observer argv
and reviewed discovery unit commands, so unrelated interactive owner commands do not
become recovery inputs. An unresolved observer CLI entry mode fails closed. This
entrypoint distinction does not change the conservative worktree policy.

The current reviewed usage is generic, not filename-specific:

| Exact path | Role |
|---|---|
| repository .env | Denial-probe inventory, no content read; Scout and root-observer unit deny access |
| holdings.csv | Scout denial plus root before/after hashing and read-only protection checks |
| out/investment.db | Root logical/file hashing and state integrity, with Scout denied access |
| root investment.db | No exact path consumer derived; a basename in validation is policy-only |

Tests cover literal-only false positives, two equal basenames in distinct directories,
constant joins/aliases, file/database hashing and denial proofs, mixed authority and
evidence, credentials that must not be content-read, fake helper names/side effects,
JSON/DB/CSV/env authority, executable/import targets, dynamic paths and wrapper effects,
and authority inside runtime folders. All prior source, import, Git, systemd, provenance,
replay, isolated interpreter and whole-worktree protections remain unchanged.

The one-time recovery remains October 25 18:30 America/New_York, daily 08:15,
Persistent=true and RandomizedDelaySec=120. No merge/deployment is authorized by
this review task; the ten-minute cutoff is unchanged. The final real inventory
audit follows exact-head validation and must stop on any rejection, with no
post-result exception.


## PR21 recovery-window update

The prior 16:30 source-only entry was never installed. The operator source
deployment rolled back before observer upgrade. Replace that entry with exactly
one October 25 18:30 Eastern recovery; do not retain the earlier absolute entry.
This prevents an expired recovery calendar from participating in Persistent=true
catch-up when the reviewed boundary is installed. Normal daily 08:15, persistence
and 120-second randomized delay remain. Complete independent upgrade verification
before 18:20 Eastern. No provenance, acceptance or financial semantics change.
0852 remains 0/3 until genuine root-bookended timer evidence qualifies.
