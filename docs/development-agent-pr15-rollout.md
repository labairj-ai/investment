# PR15 internal rollout prerequisites — 0851–0854

Owner experience: ChatGPT reviews the actual PR, exact head and CI, recommends GO
or NO-GO, and the owner replies **Go** or **No-Go**. The same Go authorizes the exact
head to merge after CI and its resulting merge SHA to deploy after merged-main CI
and technical gates. This guide is for internal release tooling/operators; it adds
no owner script, certificate handling, stage transition or second approval.

PR15 prepares source support. It does not install or activate services. All four
TODOs remain open, and all implementation/publication/merge activation settings
remain unchanged. Installation support must use reviewed, merged, clean source;
default installer invocation is plan-only. Existing installations are refused,
not overwritten. Bootstrap failure removes only newly created installation files;
an oracle that cannot be stopped retains its files for diagnosis.

## 0851: bounded static validator

`ops/validator/install.py` verifies canonical origin, exact HEAD and origin/main,
then reads the four fixed installation files from Git blobs. Its explicit apply
path is Linux root only: a dedicated nologin identity, root-controlled source,
private key/configuration, protected bare Git authority and two fixed system units.
It never downloads a model or changes an MLX/application service. The initial
allowed scope remains `docs/help/` static documentation; it grants no pytest authority.

The installer creates one fixed harmless documentation commit in the protected
Git store using Git plumbing, without a checkout or candidate code execution. It
waits for the actual oracle socket, runs a fixed off-identity key/config/socket
access probe as nobody, and records only the denial, inode/source bindings and
timestamp in root-controlled material. It then starts the fixed acceptance unit.
No owner command, certificate handling or second Go is involved.

`ops/validator/live_acceptance.py` runs as investment-oracle under the acceptance
unit's matching hardened sandbox. It requires installed root source/unit/runtime
pins, a real service invocation, private material and the fresh off-identity denial.
It exercises the installed daemon's valid document request and signed result, plus
isolated generated hostile inputs through the same installed validator source.
Timeout/crash/duplicate/truncated worker checks use actual fixed failure processes;
there is no fault-injection interface in the oracle daemon. Permission attacks,
source/runtime mismatch, active markup, executable/test/fake-result/symlink changes,
network/credential/Docker/database denials are included.

The sanitized receipt is preserved at
`/var/lib/investment-static-oracle-acceptance/live-acceptance.json` and in the service
journal. It contains the application SHA, acceptance head, source/runtime/harness
pins, service invocation, timestamps, exact matrix and L0-only scope. FAIL or missing
host identity cannot produce PASS; an in-service failure replaces an earlier PASS
with a sanitized FAIL. Generated adversarial inputs are identified explicitly and
are never a genuine discovered pilot. No secrets or database contents are exported.
Source tests cannot run as this installed service or issue its acceptance receipt.

`scripts/check_l0_validator.py` remains a functional probe, not certification.
The fixed harness must actually run on the reviewed host before 0851 can close.
A frozen-plan base still requires a protected trusted authority update; candidates
cannot write that store. Independent pytest-result authority remains a separate
runtime prerequisite and is never replaced by static PASS or this host receipt.

## 0852: read-only discovery

`ops/install_discovery_observer.py` provides plan-only-by-default root bootstrap
for the fixed observer daemon outside application source. It pins all reviewed
tracked source and the Scout unit. The daemon is read-only over application/source/
financial state and can write only its own sanitized evidence and pending bookends.
Its only child commands are fixed read-only systemd queries under the application
account with supplementary groups removed. It has no model, merge, deployment,
broker, arbitrary shell or source-write interface.

Scout's fixed root-owned before/after clients authenticate via Unix peer identity,
exact ControlPID/command line, invocation, loaded service/timer hashes/settings and
recent timer observation. Each actual timer firing is consumed at begin, so a
manual restart after interruption cannot reuse it. The installed launcher uses isolated system Python, disables
site hooks and forwards only the fixed scout command, never caller arguments.
Inside the Scout sandbox the client checks read-only source, financial/credential
inaccessibility and an unrouted network namespace. The root observer independently
measures holdings/investment/auxiliary identities, exact source/HEAD, worktree
inventory and append-only ledger history around the actual run. Unexpected Builder
activity or state transitions, changed protected state/source, failed/incomplete
signals, missing/replayed/expired bookends and manual/duplicate runs cannot qualify.

Successful observations automatically update root-controlled
`/var/lib/investment-development-acceptance/discovery.json`, outside Scout/Builder
writable state. No owner-authored JSON or manual hash capture is needed. Interrupted
or unobserved runs do not count. A new source head requires refreshed reviewed
installation pins; evidence is never silently carried to changed code.

`ops/install_discovery.py` requires the current protected observer before preparing
the six user units. Apply initializes only the private control-ledger schema and
synchronously starts the fixed read-only collector. The resulting actual spool
must be private, newly collected, parseable and have all required sources available
before any timer is enabled. Failure rolls back new units/environment files and
leaves Scout disabled. It never manually invokes Scout or installs the supervised
loop. A separately provisioned private GitHub reader must show pull=true and
push/admin/maintain=false; never reuse owner CLI credentials.

`scripts/discovery_acceptance_report.py` reads the automatic observations. Credit
still requires three distinct genuine New York timer slots/invocations, exact source,
complete counts, signal availability and current timer health. The producer cannot
create a scheduler event or make a manual run genuine. Installation and all three
real runs remain outstanding; tests and fixtures do not close 0852.

## 0853: genuine supervised pilot

The cycle checks full discovery acceptance and candidate provenance before worktree
creation and admits only L0. Independent Reviewer, protected validation, full CI,
AWAITING_OWNER and the normal exact-head owner decision remain mandatory. No-Go or
a new head invalidates downstream authority. Canonical REST PR facts fix the blank
repository identity returned by the CLI during the prior real release.

An optional operator-configured `DEV_AGENT_BUILDER_ENDPOINT` or
`DEV_AGENT_REVIEWER_ENDPOINT` selects the already-running shared Qwen MLX service
on Mac Studio port8080 (or an explicit localhost8080 tunnel). Only the existing
Qwen3.6-35B-A3B-4bit model is accepted. News port8081, other hosts/models, native tool
calls, redirects, malformed/truncated/oversized responses are rejected. Defaults
retain Ollama. No endpoint is contacted, model loaded or configuration activated
by this PR. The adapter supplies JSON only and confers no host tools or authority.

A genuine discovered improvement, accepted live validator and pytest authority,
Builder/Reviewer identities, real PR, owner decision and merged-main CI are still
required. A seeded candidate or simulated Go cannot close this TODO.

## 0854: deployment controller

The fixed installed preflight checks the dedicated identity, read-only GitHub
capability, safety stop, protected controller location and inability to replace
protected state or read known owner/application credentials. A READY permission
audit grants no deployment authority. The deployment transaction independently
rechecks the one exact-head Go, merge/main/CI, clean source, backup and health.

Installation must resolve fixed checkout privileges without giving the deployment
identity writable holdings/database parents, broad sudo, arbitrary shell or GitHub
write authority. Preflight refuses an unsafe layout rather than adding ACLs. The
existing source layout may therefore remain NOT READY until a reviewed fixed
checkout mechanism is installed. Do not turn the check off to make it deploy.

Protected comparisons and integrity-checked read-only backups include investment.db
and existing buffett.db. Code rollback never restores a database. Append-only
OWNER_MERGE and STATIC_VALIDATION audit events are recognized; unknown event kinds,
modified prefixes/schema or protected-state mutations still fail. The actual
installation, live failure/interruption matrix, delayed observations and three
controller releases remain outstanding. LOW-RISK AUTO-PR readiness is presentation
of existing evidence, never activation or autonomous merge/deploy permission.

## Explicit public discovery reader (source addition; not activated)

Discovery has two explicit operator-installed modes. `token` remains the default
and requires the existing dedicated private token plus independent
pull=true/push=false/admin=false/maintain=false verification. It cannot borrow gh
or owner credentials. `public` is an explicit choice for a verified public repo;
it never reads a token/config credential, sends Authorization, uses gh, or falls
back to authenticated access. This does not change owner/protection/CI/deployment
clients or grant merge, PR publication, implementation or deployment authority.

The internal installer accepts `--reader-mode public`; its default remains token.
It persists `DEV_AGENT_DISCOVERY_READER_MODE` and the verified target
`DEV_AGENT_DISCOVERY_REPOSITORY` in collector.env. Public mode omits token settings.
The owner does not need to operate this configuration or supply structured comments.

Public transport uses fresh credential-free urllib openers with ambient proxies
and authentication handlers excluded. Only these exact HTTPS GETs are permitted:

- `https://api.github.com/repos/{reviewed-owner}/{reviewed-repo}`
- `https://api.github.com/repos/{reviewed-owner}/{reviewed-repo}/actions/runs?per_page=10`

Redirects must stay within those exact URLs at api.github.com. Other hosts,
schemes, repositories, queries, write routes and methods are rejected. Repository
metadata must have the exact canonical full_name, private=false and visibility=public
before and after every workflow collection. No visibility cache or authenticated
retry exists. A private/missing repository or HTTP403/429 stops that collection.
GitHub documents public unauthenticated access for these
[repository](https://docs.github.com/en/rest/repos/repos#get-a-repository) and
[workflow-list](https://docs.github.com/en/rest/actions/workflow-runs#list-workflow-runs-for-a-repository)
GETs; [rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api)
remain binding, never a reason to borrow another identity.

Collection invalidates the old spool before attempting network access. A failed
collection persists unavailable sources and exits nonzero; interruption/publish
failure leaves no usable old spool. Scout rejects spools lacking CI, telemetry or
performance availability before candidate discovery. The unchanged real timer
requirements, independent host bookends, L0 scope and all activation flags remain
mandatory. Source tests do not install/enable the reader or count as live runs.


## Pre-discovery observer pin refresh (source only; not applied)

The root observer was bootstrapped at `05d6cccf734d4604d1a8c10406d9e3d7598e9c6f`.
PR17 merged as `88f1757af1ed090983ce262a1936a41dbf8a279b`; neither that release
nor this refresh change has been deployed. The discovery installer must continue
to reject a different config.head; bootstrap must continue to refuse an existing
observer. This refresh does not bypass either guard.

After a separately owner-reviewed merged release is deployed through the normal
release path, an internal release operator may plan the bounded transition with
`ops/install_discovery_observer.py --root /home/optiplex/investment --head NEW_MAIN
--refresh-from EXPECTED_OLD_MAIN`. Without `--apply` it performs no filesystem or
service mutation. This is internal release tooling, not an additional owner
approval, promotion or manual owner workflow. It never installs discovery units.

Apply is only supported on the fixed Linux root layout with a clean exact target
HEAD equal to origin/main, protected exact old Git-derived config, and unchanged
observer executable, root unit and Scout service/timer Git objects. It verifies
loaded systemd protections, process/runtime identity and the private socket; a
fixed rejected root request cannot invoke Scout or produce a host bookend. It
requires no user discovery units, spool, worktree, timer history or acceptance
artifacts. A pending SQLite ledger journal is refused; the ledger is inspected in
memory without side files. No accepted runs are migrated, erased or reset.

Under an exclusive root lock it rechecks preconditions, durably saves the exact
prior config, verifies the observer stopped, fsyncs a new file and atomically
replaces only config.json. It restarts only the root observer and independently
checks its new invocation/socket, runtime, config, unit digests, full target
manifest and unchanged disabled/SHADOW/human-merge controls. No daemon-reload,
source writes, investment writes, user-unit install or timer enable is permitted.

Failure restores the exact saved config and revalidates the old observer. That
result is explicitly NOT READY against a new source checkout. If rollback cannot
be verified, the tool attempts and verifies a stop; if even stop is unconfirmed it
reports that explicitly. An unrestored configuration is quarantined away from the
authoritative path when possible, never treated as trusted recovery. Recovery
material is retained for diagnosis; the tool never deletes an existing observer
or starts bootstrap to bypass the upgrade guard. Executable/unit changes require
a separately reviewed full upgrade, outside this config-only mechanism.

Operational acceptance remains 0/3. No host refresh or discovery installation has
been performed by this source work. L0-only scope and one Go/No-Go authority remain.
