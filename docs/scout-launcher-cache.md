# Lifecycle-independent migration launcher cache

PR25 starts at e96e04827d03adfb30cf14a1dd6d91381bcdcae0 (0852; 0853 remains blocked).
The isolated migration/influence launcher uses
`/var/cache/investment-discovery-reviewed-pycache`; its required existing parent
is `/var/cache`. PLAN_ONLY creates no cache directories. Existing final prefixes,
including dangling symlinks, must pass the protected ancestry contract.

Before the migration import the launcher only parses fixed arguments, requires
isolated/no-site flags, fixes bytecode settings, performs the standalone source
influence audit, requires the expected boundary argument and system interpreter,
and validates the cache ancestry. The audit reads source, Git and installed unit
identities; it does not require an observer socket, active PID, timer activation
or observer RuntimeDirectory. The cache check was the only pre-import dependency
on the stopped observer's RuntimeDirectory. No systemd reload or state mutation
occurs before import. Runtime observer and Scout caches remain unchanged.

Tests exercise the launcher with real source influence auditing and the existing
synthetic stopped host transaction (disabled user timer, absent system timer,
zero acceptance). Linux runs the regression in system Python -I -S with real
/var/cache ancestry; portable tests model ancestry attacks without host changes.
The production PLAN_ONLY remains subject to the existing strict 15:50 cutoff;
after that time it must return ACTIVATION_WINDOW_EXPIRED, never bypass the guard.
No schedule, acceptance, migration stages or recovery boundaries change.
