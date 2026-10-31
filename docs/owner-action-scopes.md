# Versioned owner action authority and Scout merge-only bootstrap

Risk L5. Source work only. This change issues no owner decision and grants no
permission to install a connector, merge a PR or touch production.

## Exact object and trust boundary

Header: `OWNER-AUTHORIZATION solo-owner-3\n` (an actual newline).
The JSON object has exactly these fields:

| Field | Contract |
|---|---|
| repository, pr, head | Exact repository, positive PR number, 40-character reviewed PR head |
| action | MERGE_ONLY or MERGE_AND_DEPLOY; no default or rationale interpretation |
| risk | L5 for every new action object, even for a lower-risk source diff |
| decision | APPROVE, REQUEST_CHANGES or DEFER |
| financial_ack, execution_ack | Explicit true for new action authority |
| owner_login, owner_id | Exact personal owner matching GitHub and external bindings |
| nonce | Fresh single-use 16–128 character alphanumeric/hyphen identifier |
| issued_at | Numeric UTC Unix timestamp, within 60 seconds of GitHub object creation |
| source_head | Exact separately reviewed issuer bundle SHA from external policy |
| policy_hash | SHA256 of the canonical external owner policy |
| rationale | Nonempty review explanation; grants no action |

GitHub supplies the authenticated human actor, allowed application, canonical
comment URL and PR association, and immutable creation timestamp. Edited objects,
wrong owner/app/PR/head, duplicate JSON keys, nonfinite data, invalid acknowledgments,
source/policy changes and superseding decisions fail closed. The object is reread
after validation. The append-only isolated authority ledger rejects nonce reuse
with a different object/context; same-object ingestion is idempotent evidence,
not a second merge. The merge action expires after one hour and is exact-head and
immediate; successful merge is recorded and cannot be replayed. Delayed deployment
may revalidate the original explicit deployment action without a daily approval
ceremony: issuance freshness is bound to GitHub creation, while CI/health gates
retain their own independent freshness requirements.

External owner bindings add `issuer_source_head` and `authorized_actions`. They
must be protected operator configuration outside candidate source, provisioned by
a separately reviewed owner connector rollout. Missing bindings grant no scoped
action. `MERGE_AND_DEPLOY` is available only if explicitly listed. Verify the
actual installed bundle against that SHA, including all imported modules and
entrypoints; a payload claiming a source SHA does not install or certify an issuer.
Read-only deployment credentials cannot issue owner decisions. Scout and Builder
must have neither owner credentials nor connector filesystem/process access.

## Consumers and migration

The owner connector emits only v3 objects with an explicitly selected action.
The merge gate requires current authenticated v3 authority, exact-head successful
CI and the existing human merge policy. GitHub receives one immediate merge PUT
with the expected head; its actual owner merge actor is verified afterward.

Deployment admission requires MERGE_AND_DEPLOY before any authority-ledger write.
The new poller filters the v3 header, verifies the deployment action before queueing,
and never queues MERGE_ONLY. The transaction boundary independently validates the
embedded action and identity and repeats current admission before any receipt,
service or source mutation; it checks scope again before stopping the service.
Changing a top-level action flag cannot alter the embedded authenticated binding.
Activation consumers also require deployment-authorizing scope. Existing financial,
source, backup, CI, health, runtime and rollback controls remain mandatory.

Legacy v2 objects are historical evidence only to the new action gates. There is
no conversion or compatibility deployment fallback. Upgrade the isolated owner
connector, check publisher and deployment controller together in a separately
reviewed rollout. Existing v2 releases awaiting deployment will block pending an
explicit new scoped decision; do not rewrite their evidence. Do not downgrade a
v3 header to satisfy old consumers.

Frozen byte-exact a27 copies of the old deployment poller and GitHub verifier are
kept in tests/frozen, plus the exact PR34 transition authorization function. The
legacy poller filters on the old v2 header both in recent comments and when
rediscovering current-main PR comments. Tests fail if any new verifier or admission
is reached for v3 merge-only objects, including repeated/concurrent polling. This
proves old-code non-discovery, rather than relying on newly installed guards.
The unchanged Scout transition requires a different protected capability, exact
old/merged source, historical receipt binding and exact transition rationale;
merge-only v3 does not satisfy it. No Scout runtime qualification rule is changed.

## PR34 ordering and bootstrap

Do not merge this governance PR into main before Scout's initial epoch transition.
It changes files outside PR34's deliberately narrow allowed diff and would block
the initial a27-to-repair transition. Keep PR34 at
`1f25e72001db978228050c6f342bc5bcfe477843`; keep production and GitHub main at a27
until the owner separately authorizes the exact Scout merge. No bootstrap step
moves production HEAD.

Preferred future sequence (not executed by this task):

1. Review the exact governance bundle SHA and its full CI, frozen-poller proof,
   bootstrap code, policy and credential isolation. Obtain explicit owner authority
   to provision only the isolated owner-side connector/check publisher from that
   reviewed bundle, outside main and production. Verify all module hashes, OS
   restrictions and issuer_source_head/policy_hash. Use a private separate authority
   ledger; never the production development ledger. The bootstrap policy permits
   only MERGE_ONLY. No deployment agent, application service or Scout is updated.
2. Verify PR34's exact head, old main/base, mergeability, all required branch checks,
   native v255 and full eight-gate CI, influence evidence and preserved production
   state using read-only procedures. Freeze the evidence for the human owner.
   Require a complete PR34 approval inventory with no v2 owner objects: a v3 decision
   cannot revoke an older deployment-capable v2 object for an old poller that cannot
   see it. Concurrent legacy owner-object creation must abort bootstrap admission.
3. The authenticated owner deliberately selects MERGE_ONLY with fresh nonce,
   timestamp, L5/domain acknowledgments and exact PR/head/source/policy identity.
   `owner_gateway.scout_merge_only` is a fixed owner-side API, not a Scout/Builder
   command or generic shell endpoint. It restricts repository, PR34/head/base,
   bootstrap policy and CI, records v3, rechecks inventory and boundary, and invokes
   exactly one expected-head GitHub merge through the existing owner mechanism.
   Preserve the actual GitHub object, owner actor, resulting merge SHA and authority
   ledger receipt. Do not call generic deployment continuation or epoch controllers.
4. Require merged-main native v255/full-suite/eight-gate/influence PASS on the actual
   Scout merge SHA. Verify production remains a27, historical 1/3 and five candidates
   intact, observer/timer unchanged. A CI failure blocks the future transition.
5. Only a later separately authenticated exact-source L5 decision may authorize the
   reviewed epoch procedure. No conventional deployment. It must retain historical
   1/3 and start the repaired deployed source at 0/3. No fixtures/manual runs earn
   qualification. TODO0852 remains incomplete; 0853 blocked; PR19 unmerged.
6. Review governance integration against the actual post-transition main and merge
   this PR only under its own owner decision/dependency ordering. Later source
   changes need a separately reviewed epoch-aware release path.

If the isolated connector cannot safely be provisioned before this PR merges,
the human owner can perform an audited GitHub-only bootstrap: personally post the
new v3 MERGE_ONLY object from their authenticated GitHub account, have a separately
reviewed read-only v3 verifier/check publisher validate all bindings and nonce,
then personally perform the immediate exact-head GitHub merge. Preserve GitHub's
owner actor, object, check and merge evidence. This is an explicitly owner-performed
procedure, not agent authorization or permission to bypass branch protection.
If an existing required check cannot validate v3 without safe owner-side provisioning,
or credential isolation, old-poller non-consumption, approval inventory or exact-head
merge cannot be proved, STOP: bootstrap remains BLOCKED. Do not emit v2 APPROVE,
disable the deployment poller, override checks or reinterpret rationale to proceed.

Operational bootstrap remains BLOCKED until this owner-side isolation/provisioning
or human-performed audited path and new deliberate decision are actually accepted.
Source tests alone cannot certify an installed connector or grant merge authority.
