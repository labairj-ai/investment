# Completed oneshot certification identity (PR30)

Base: dd1ef4d4de581ada1d29fc451f3872b6b1e43cf0. Scope is TODO 0852;
0853 remains blocked and PR19 remains held/unmerged.

The October 28 07:47 EDT attempt returned start rc=0, Result=success and
ExecMainStatus=0, but the completed Type=oneshot unit had InvocationID="".
PR29 rejected that property before querying the journal. Rollback completed.
This is a manager-state retention assumption, not evidence that a sandbox probe
failed. It does not justify weakening provenance or granting acceptance credit.

Read-only queries of the retained journal, bounded to the certification unit and
the recorded start/failure interval, recovered exactly three reports with one
trusted invocation 407a9628d7ba4abf90b0ef6ab0968487. They share boot
f0ea0f99d0fa4b0684cec1c430cdb35e and optiplex UID1000; distinct PIDs2213790,
2213794,2213801 and increasing realtime/monotonic timestamps corroborate the
three executions. Every safety boolean is true, test_evidence_only=true and
accepted_scout_run=false. The broader bounded unit window contains only these
reports and PID1 start/completion messages, with no competing execution.
[Sanitized fields and reports](evidence/scout-certification-20261028.json) omit
arbitrary journal messages. They are retrospective diagnostics, never acceptance.

The correction captures kernel boot identity, expected account UID and monotonic
time before the single synchronous systemctl start, and realtime/monotonic upper
bounds immediately after return. It preserves unit identity, start rc, Result,
ExecMainStatus, exact installed source/sandbox and all existing migration gates.
The journal query filters by trusted _SYSTEMD_UNIT and both realtime bounds; it
does not filter by a proposed invocation, which could conceal competing IDs.
Every returned record must carry one valid nonzero _SYSTEMD_INVOCATION_ID, exact
unit/boot/UID, positive PID, stdout transport and canonical bounded timestamps
inside both clocks' execution interval. Unprefixed application fields have no
identity authority. Duplicate-valued/array metadata fails closed.

Exactly three exact-schema reports must pass literal boolean checks, with three
distinct journal PIDs in increasing monotonic order. The unchanged fixed script
prints once per process, checks its current manager-owned per-command record,
and executes separately under ExecStartPre/ExecStart/ExecStopPost. Thus duplicate
reports from a phase process fail; no caller phase label is accepted as proof.
Any valid nonempty manager InvocationID must equal the unique journal ID. Empty
or omitted manager identity is accepted only after the same complete journal
validation. Malformed/nonzero-invalid manager IDs, competing IDs, missing trusted
fields, wrong identities, stale/out-of-window records and bad counts fail closed.

Systemd documents underscore-prefixed fields as journal-owned and distinguishes
them from application-supplied metadata:
https://www.freedesktop.org/software/systemd/man/255/systemd.journal-fields.html

The durable root0600 bounded atomic/fsynced trace records manager presence,
execution bounds, journal identity decisions, identity source, matching count
and final decision. Existing rollback retains it. Specific allowlisted codes
identify journal identity/unit/boot/UID/window, process and manager mismatch
failures. Raw messages and credentials are never persisted in the trace.

The certification unit/script, lifecycle, sandbox, Scout schedule, financial and
execution behavior, activation configuration and zero-credit contract are unchanged.
The empty-manager regression fails on PR29 and passes with this correction.
All rejected full-migration fixtures require rollback and zero credit.
No production certification, migration, timer normalization or activation is part
of this source task. The October28 one-APPLY approval is consumed and is not reused.
