# Durable Scout sandbox certification decisions (PR29)

Base: 1843f81f2c71eb1076907fb8f1d2ac0687ea24db. Scope remains 0852;
0853 remains blocked and PR19 is not merged by this change.

PR28's certification failure remains unresolved. Retained reports and successful
fractional, integer and InvocationID-only journal replays do not prove a timestamp
defect or reconstruct missing post-run systemd properties. This change adds
observability, not a speculative functional repair.

Each certification attempt now creates certification-trace.json in its existing
root-protected migration backup. The fixed versioned evidence includes the attempt
and target identities, exact Python numeric start representation, current step,
completed decisions, sanitized observations and terminal PASS/FAIL. Atomic writes
use exclusive nonsymlinked temporary files, mode 0600, root ownership, file fsync,
rename and directory fsync. The serialized trace is limited to 16 KiB. Rollback
retains the backup and trace. Persistence failure is itself fail-closed.

The trace records identity property comparisons, explicit start return code and
output lengths, allowlisted post-run properties, the exact fixed journal command
and since argument, query result/lengths and bounded parsing counters. Missing
properties stay null; arbitrary invalid contents are classified rather than
copied. It never stores stderr, command stdout, unrelated journal MESSAGE content,
credentials or financial data. A failed assertion is persisted before raising a
specific allowlisted certification code at SANDBOX_CERTIFICATION_PASSED.

The start command is unchanged and runs once. Its nonzero return code is rejected.
The invocation syntax, journal time filter, 65,536-character journal bound,
strict JSON decoder, exact report schema, literal boolean checks and exact-three
report requirement remain fail-closed. Sandbox units, Pre/Main/Post execution,
acceptance credit, financial/execution code, schedule and cutoff are unchanged.
Certification remains test evidence and cannot grant Scout acceptance credit.

Disposable full-migration tests inject each failure and require successful
rollback, retained exact failure evidence, protected-state equality and zero credit.
The fixture now dispatches through its current invoke callback so injected failures
actually reach the real migration. The positive regression preserves the fractional
since argument and validates three reports, without claiming to reproduce the
unresolved historical PR28 failure.
