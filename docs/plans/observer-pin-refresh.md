# Pre-discovery observer pin refresh

Base: separately merged PR17 main `88f1757af1ed090983ce262a1936a41dbf8a279b`.
Risk L5: root-controlled trust configuration and service lifecycle. No host apply,
deployment, discovery installation, Scout invocation or acceptance evidence in this task.

The real host remains at05d6cccf with an active observer pinned to that exact head.
Discovery installation checks config.head against its exact source; bootstrap
refuses existing observer paths. Preserve both guards. Old/new observer executable,
root unit and Scout service/timer Git blobs are byte-identical; require that property
at every refresh. Executable/unit/runtime-boundary upgrades are out of scope.

Add --refresh-from EXPECTED_OLD to the existing tool, still plan-only absent --apply.
Require fixed Linux root/layout, clean exact target main/origin, root-protected old
config/source/unit, full old Git-derived config equality, unchanged four identities,
verified loaded process/runtime/socket boundary, and no user units/spool/worktrees/
scheduler records/root acceptance artifacts. Build the new full manifest only from
exact Git blobs and compare tracked checkout bytes. All implementation flags remain
false, SHADOW, riskL2, human merge required. No accepted evidence is moved/reset.

Apply rechecks under an exclusive root lock after read-only preflight, durably backs
up the exact old config, stops only the observer, fsyncs/replaces only config.json,
then starts/revalidates that observer and its new socket/invocation. No user unit,
source, investment state or spool writes. On failure restore exact old bytes/mode
via the durable backup and restart/revalidate the unchanged old installed boundary.
Because the checkout is already at the new head, rollback remains NOT READY for
new-head discovery. If rollback cannot be demonstrated, stop the fixed observer and
report failure, never success; do not delete an existing observer to bootstrap it.

Test successful and no-op plan paths, all preconditions/tampering/changed binaries,
atomicity, service/socket/postcheck failures, exact rollback and failed rollback,
no acceptance carry-forward or unintended writes. Run focused observer/discovery,
public-reader and full tests plus all eight unchanged gates and real exact-head CI.
Open a separate PR and stop for review. Never apply this code on OptiPlex in this task.
