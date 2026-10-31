# Current-Job Scout provenance and history-preserving source transition

Source-only recovery for TODO 0852. No merge, production execution, deployment,
timer control, acceptance credit or implementation authority is granted here.
PR #19 remains separate and deployment-blocked. TODO 0853 remains blocked.

## Incident and corrected contract

Production is a27bed1ebd3a69df5723212784842df456e153b3. October 29's accepted
invocation is 8608a7c10e9b4c23b96cf91bcc8fa51f, slot scout:2026-10-29, five candidates.
October 30's rejected invocation is 77541c9232d74e578d6d0f596cce954d. Its timer fired
at 16:00:16.896108 EDT; Pre failed, Main never ran, Post failed. No credit is added.

systemd 255.4-1ubuntu8.18's unit_start retains existing Unit.ActivationDetails;
timer_enter_running attaches the current firing to the activation Job instead.
The October 30 current timer monotonic value was 6893457894997 while the retained
Unit value was 6807047895028. This is retention, not a delayed update to wait for.
Relevant upstream sources are systemd v255 src/core/unit.c, timer.c, job.c,
dbus-job.c and service.c. Exact Ubuntu 255.4 source/patch archives and sanitized
host evidence were inspected independently; no historical live Job was captured.
Do not present its presumed contents as an observed October 30 fact.

Both the standalone installed observer and the scheduler's reviewed source invoke
the same contract independently during active Pre and oneshot Main. Root never
imports writable repository code. Main runs unprivileged and imports the reviewed
repository copy, already bound to the protected installed observer digest and SHA.

The contract requires exact service/timer files, unchanged sandbox/manual-start
refusal and no incoming activation dependencies; current command PID, argv, phase,
manager InvocationID and execution bounds; current Unit.Job ID/canonical object
path; Job.Id/Unit/JobType=start/State=running; exactly one timer trigger with typed
realtime and monotonic values equal to the current timer; current boot and clock
bounds. Timer firing must fall within the reviewed 16:00–16:02:59 Eastern window,
and the timer must already have been active before the 15:50 cutoff. A manually
restarted persistent catch-up cannot substitute for the natural daily slot. It rereads all job/fire identities and the active command record and
revalidates the service properties and installed file hashes. Missing, stale,
conflicting, malformed, unavailable or racing evidence fails closed. No fallback
to Unit.ActivationDetails, caller-supplied environment or timestamp proximity exists.

Job details establish a genuine timer contribution to the current activation;
systemd calls them best effort and does not enumerate every merged trigger. The
locked unit graph, no incoming dependency activation, refusal of manual starts
and manager-owned current Job are all necessary. Unknown trigger fields/conflicts
are rejected. A privileged administrator changing PID1's world is outside the
unprivileged Scout trust boundary; this does not grant operators an alternate
accepted execution path. Duplicate invocations, timer fires and slots still fail.
Stop-post uses the authenticated begin evidence and final execution/SCHEDULE join;
it does not assume the activation Job survives until Post. New receipts retain
begin Job/fire/boot evidence. Synthetic certification earns zero credit.

## Qualification epochs

The protected config may select acceptance_epoch=<exact source SHA>. Observer and
scheduler health select only epochs/<SHA>/discovery.json. No new receipt is created
until a complete genuine run succeeds. An old-source receipt can never be replaced
by a different source through the normal observer path. The legacy discovery.json
remains historical, with a durable archive copy plus timer-fire and sanitized
October 30 failure evidence. Existing candidate IDs and ledger rows stay unchanged.
New source begins 0/3; old a27 history remains 1/3. Old credit cannot qualify new
source or authorize a prior candidate for implementation under a different SHA.

## Transactional release path

Existing zero-history upgrade and USER-to-SYSTEM migration remain unchanged and
must reject this host. epoch_upgrade is a separate fixed root release adapter;
it never installs/changes/reloads/restarts Scout units or controls their timer.
Its target must be exact merged origin/main, with a clean exact old source and a
narrow nonfinancial diff (Scout implementation, tests and documentation only).
All three unit files remain byte-identical. No timer stamp is removed or rewritten.

The trusted release controller must stage the exact merged target's Python source
under /var/cache/investment-discovery-epoch-source/<SHA>, root-owned, no writable
or symlink ancestry, after verifying source/CI and before invoking privileged code.
Use system Python -I -S, protected reviewed pycache prefix and dont_write_bytecode.
The adapter verifies the fixed staging root and hashes every loaded repository
module against target Git blobs. Never import this root tool from the live
user-writable checkout. PLAN_ONLY inspects; APPLY additionally requires the root
release-controller capability at /etc/investment-discovery-observer/
scout-epoch-authorization.json. The explicit --authorize-owner-object <comment-id> mode can mint this capability only after authenticating the actual owner object and rechecking production preflight. It does not APPLY or stop any service. Existing capability files are never overwritten.

The capability's exact schema is checked by authorization(): solo-owner-1 verified
human GitHub object URL, repository, scope=scout-source-epoch-transition-once,
old_head, reviewed PR head, merged target/CI SHA, PASS, fresh timestamp, nonce,
APPROVE, L5, the exact historical receipt hash/count and both domain acknowledgments. Both capability issuance and APPLY independently authenticate the human object through existing solo-owner governance, check revocation/current context and verify merged-main CI. The owner rationale must be exactly `scout-source-epoch-transition-once:<old SHA>:<merged target SHA>`; its nonce must match. GitHub access requires the separately provisioned read-only credential and protected owner bindings, never owner CLI credentials. The latest exact merged-main Tests run must pass both native-systemd255 and test; the latter enforces all eight release gates.
A root attestation is a privileged release capability, not an application JSON
claim; a user/model cannot create it. Controller integration and its actual owner
receipt are mandatory operational review gates. This PR does not manufacture one.
October 28/29 migration authorizations have the wrong scope/source and cannot work.

APPLY rechecks authorization and complete preflight under an exclusive root lock,
consumes the nonce with exclusive attempt-directory creation, fsyncs the backup
plan and append-only stage journal, stops only the observer and checks zero Scout
PIDs/no queued Job again. It archives history before switching source as optiplex,
atomically replaces observer bytes and commits config/epoch selection last. The
observer is stopped throughout the multi-file transaction, preventing mixed-source
Scout execution; no claim of an atomic filesystem-wide Git checkout is made.
Only a completely verified coherent generation may restart the observer.
Pre and Main also require a root-owned COMMITTED transition marker, written only
after post-start verification; an interruption before that marker cannot execute
Scout even if the observer process has restarted.

Verification checks source influence, exact source/config/unit identity, timer
stamp bytes/inode/mtime and manager history, old receipt/fire history, ledger
prefix/schema and allowed append-only scheduler observations. Financial files,
sidecars, holdings and SHADOW controls are compared within the transition by
read-only hashes; no financial SQLite connection or restoration occurs. An
unrelated live update makes proof ambiguous and aborts. The development ledger is
read into query-only in-memory SQLite, avoiding production WAL/SHM side effects.
A quiet window >600 seconds is required and rechecked before source writes.

Every caught failure stops the observer, restores only source/observer/config,
verifies the old boundary and restarts only that observer if rollback is proved.
The exact failure stages remain; no automatic retry, acceptance reset, financial
restore or Scout start exists. If rollback/quiescence is unverified, the observer
must remain stopped and intervention is required. A process crash leaves its
fsynced plan/journal; explicit --rollback <consumed nonce> under the same lock
can only restore, never resume APPLY. Completed attempts cannot be replayed.
Archives and new-epoch evidence are never deleted on failure. A timer firing during
an observer outage fails Pre and receives no credit; no catch-up is manufactured.

## Validation and operational exclusions

Fixtures cover three consecutive daily activations with retained Unit metadata,
both consumers, manager/identity/phase/clock/race attacks, zero receipt on rejection,
replay/duplicate controls, source epoch separation, root capability rejection,
archive preservation, every transaction stage failure, crash recovery and failed
rollback. Existing sandbox, financial, CC and governance contracts remain required.
Fixtures and CI are source validation, never live qualification or deployment proof.

Before any production transition: exact-head owner review, actual authenticated L5
capability/controller verification, merged-main eight-gate PASS and supported-host
influence PASS; reviewed staging/rollback rehearsal and a quiet natural timer window.
After transition, observe three independently genuine daily runs in the new source
epoch. Keep ECC, Builder, autonomous implementation, publishing and auto-merge off.
October 31 must stand on its actual evidence and cannot inherit October 30 credit.

CI's source audit uses a fresh Git-object clone because actions/checkout adds
temporary credential/worktree Git interpretation settings. The auditor still
rejects those settings; no production rule is relaxed. Host preflight separately
audits the actual production checkout for both old and target source graphs.

Transition quiescence also inspects bounded process arguments for fixed Scout
wrapper and CLI entry points outside the unit. Production discovery rejects an
operator-classified trigger before migrate/event/candidate writes, including
alternate root spellings or a caller pointing a different root at the production
ledger. Disposable nonproduction fixtures retain their existing manual test path.

## Sealed history and status consumers

The archive is published exclusively at
`/var/lib/investment-development-acceptance/history/<old SHA>-<manifest SHA256>`.
Its directory mode is 0500; files are 0400 and root-owned. The canonical manifest
contains exact hashes and sizes for discovery.json, timer-fires.json, sanitized
October 30 failure evidence, ledger-history.json and candidates.json. Every member
and the complete inventory are checked before epoch commit and by the root observer
on subsequent bookends. Existing archives and incomplete staging evidence are never
replaced or deleted. These are sealed, content-verified historical artifacts, not a
claim that root cannot change storage. Any mismatch fails closed.

The public root-owned COMMITTED marker includes the old source, slots, count and
manifest hash. Status/watchdog consumers receive explicit `epochs.historical`,
`epochs.current_source` and `current_epoch_accepted_runs`. Historical 1/3 is displayed
separately and cannot satisfy the new-source threshold. In a new epoch even the
first credit requires the root receipt to join the exact source's successful ledger
collection; missing/invalid transition or observer evidence reports zero credit.

Native proof uses Ubuntu's pinned systemd 255.4-1ubuntu8.18 in a disposable Docker
container in CI, no host mounts or production data. The fixture is RefuseManualStart
and receives three natural short-interval timer activations. Both Pre and Main read
actual D-Bus Job/Unit/Timer and execution records; a separate validator proves fresh
Jobs, unique invocations, current commands and retained Unit activation metadata.
Artifact `scout-systemd255-native-proof` preserves raw non-sensitive fixture records
and the result. The runner refuses the production layout. Fixture metadata explicitly
states `fixture_only=true` and `accepted_scout_run=false`; it creates no Scout credit.

PLAN_ONLY never probes the observer socket or consumes approval. A blocked preflight
returns `PLAN_ONLY_BLOCKED`, `changes_applied=false`, and readiness failure details;
a successful plan lists source, historical slots, candidate count, fingerprints,
timer/observer identities, intended changes and archive/rollback requirements.
