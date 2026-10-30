# Scout migration accepts reviewed deployed checkouts (PR27)

Base: afc0d2c0e8bc8c0559cb663edc086368cc4a9366. Scope: 0852; PR19 remains
held and 0853 blocked. No Scout redesign or schedule change.

`deployment_agent.executor.Executor.checkout()` fetches reviewed HTTPS main
into FETCH_HEAD, proves target ancestry to FETCH_HEAD, then checks out the exact
SHA detached. It does not update or attest a cached origin/main. In contrast,
PR26 migration used `pin_refresh.prepare -> install_discovery_observer.prepare
-> validator.install.prepare`, requiring cached origin/main equality, and also
required a local branch named main. Those contracts reject valid deployments.
The integration regression runs the actual Executor checkout with private bare
Git transport, proves detached exact HEAD with a stale or absent cached ref,
proves the old generic prepare rejects it, then runs real migration PLAN_ONLY
with real influence auditing and synthetic stopped-host/financial state.

The observed host at task start was still attached to main with matching cached
origin/main. Therefore the source integration mismatch is proven, but it alone
is not proven to explain PR26's prior sanitized live preflight failure. New
allowlisted diagnostics distinguish the actual rejected invariant next time.
No production branch/ref was manually repaired.

Migration-specific source validation requires fixed canonical root, exact target
commit object, HEAD equality, tracked cleanliness, exact expected repository
origin URL, OLD_HEAD ancestry, safe Git metadata/configuration and a complete
regular-file manifest read from target Git objects and matched to checkout bytes.
It rejects unsafe hooks/filters/replacements/alternates/submodules, including
hidden manifest changes despite index assume-unchanged flags. A local main branch
adds no authority. Detached HEAD passes; cached remote refs are not consulted.
No network fetch or GitHub credential is used by migration.

Owner/main/CI and successful protected-state-preserving deployment authority is
established by the immediately preceding Deployment Agent A0/A1 transaction.
The migration source checker does not independently attest that external authority.
A fixed root-controlled deployment receipt/config path is not installed on this
host; current release receipts have UID1000-owned ancestry. Consuming them as root
trust would be unsafe, so this uses the explicitly authorized exact-Git-object
fallback. It adds no user-writable receipt assertion or new receipt coupling.
Deployment Agent checkout, rollback and receipts remain unchanged in source.

Preflight emits sanitized allowlisted codes: DEPLOYED_SOURCE_SHA_INVALID,
DEPLOYED_SOURCE_DIRTY, DEPLOYED_SOURCE_AUTHORITY_INVALID,
REPOSITORY_ORIGIN_INVALID, OLD_BOUNDARY_INVALID, STOPPED_OBSERVER_INVALID,
OLD_USER_SCOUT_BOUNDARY_INVALID, ACCEPTANCE_PRECONDITION_INVALID,
OPERATIONAL_SIGNALS_MISSING, SYSTEM_BOUNDARY_COLLISION, SYSTEM_UNIT_STATE_INVALID.
Existing time/history/protected-state codes remain. No raw exception text is emitted.

Keep `/var/cache/investment-discovery-reviewed-pycache`, stopped-state launch,
NORMAL_ACTIVE/STOPPED_ROLLBACK, root progress receipts/rollback, real separate
certification, manager-owned execution proof, no simultaneous timers, protected
state and zero-credit acceptance rules. Daily schedule remains exactly one
`OnCalendar=*-*-* 16:00:00 America/New_York`, Persistent=true,
RandomizedDelaySec=120, Unit=development-scout.service. Cutoff remains 15:50;
first next elapse must be today16:00–16:02. No history reset or one-time calendar.
