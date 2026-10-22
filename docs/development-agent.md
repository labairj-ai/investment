# Development Agent

Tasks 0760–0784 implement a software-development control plane. It has a dedicated
`development-control.sqlite3` store outside the repository and investment databases.
The ledger contains immutable candidate snapshots and append-only events. No module
imports the portfolio, recommendations, broker or investment-learning database.

Run `python -m dev_agent.cli init`, then `python -m dev_agent.cli scout --root .`.
`list` and `show --candidate ID` inspect the queue. Discovery is bounded, deterministic
and creates proposals only. Explicit operational signals may be supplied as JSON with
`--input`; missing CI/telemetry remains unavailable. Sources include user feedback,
test/CI failure, error/health/performance/accessibility observations and static debt.
Architecture exclusions require a human rationale; file size alone never authorizes
refactoring. Raw model prompts and large logs are not persisted.

`plan --candidate ID --input criteria.json` writes a collision-safe TODO. Commit the
plan through the normal reviewed workflow, then `bind-plan` pins the clean commit.
`decide --candidate ID --decision approve --nonce UNIQUE --input context.json` is an
explicit human action. L3+ requires `--rationale`. Approvals bind scope, TODO acceptance,
risk and base SHA. A new scope/SHA requires a new plan and approval. Stale/replayed
decisions fail. `worktree --candidate ID` creates a pinned isolated agent branch.

`build` requires separate provider contexts, a digest-pinned preprovisioned Docker
image, current certification and verified GitHub protection. It accepts structured
text writes, not shell commands. The model never receives OS tools or secret files.
Container validation has no network, host credentials/socket, writable source mount,
capabilities or privilege escalation. Missing Docker returns UNAVAILABLE. No image
pull is performed. Run without privileged Docker/host mounts. Container dependencies
must already exist in the approved image. Logs are discarded until a reviewed,
bounded artifact export is configured; do not infer test counts from model output.

Runner budgets cover action count, written lines, iterations, wall time and repeated
high-severity findings. Exact head/source hashes invalidate stale evidence. The reviewer
receives original requirements, diff and validation, never builder private rationale.
It has no write tools. High-risk financial/execution/governance changes remain in the
supervised human workflow even with model PASS. Review PASS is not PR-ready or merge
approval. PR handoff requires every mandatory test/gate, SHA-bound receipt and verified
protection. It never pushes, merges or enables auto-merge. The operator pushes only
the scoped task branch before handoff. Existing PRs are updated, never duplicated.

## GitHub protections and break glass

Required main protection: PR, at least one independent review, dismissal of stale
reviews, last-push approval, strict current-head `test`, conversation resolution,
restricted push, no force push/deletion, no admin or agent bypass. `protections`
reports FAIL/UNAVAILABLE when absent or unauditable. A human administrator must
configure protection and independently audit the agent identity and active rulesets;
the agent never grants itself permissions or edits rulesets. Break glass requires
a human administrator, incident rationale, before/after settings, a separately
reviewed emergency PR and restoration evidence. It cannot silently count as agent
approval. Auto-merge stays disabled for every level; possible future L0–L1 support
requires a separately reviewed policy change and new evidence.

## Golden engineering principles — engineering-principles-1

- P1: Single source of truth; never mutate authoritative investment state.
- P2: Deterministic financial arithmetic and explicit unavailable states.
- P3: Immutable SHA-bound evidence; missing evidence is not PASS.
- P4: Minimal duplication and bounded model authority.
- P5: Mobile usability and explicit human review for protected behavior.
- P6: Fail closed; never relax gates, tests or this contract to obtain PASS.

Planner, builder and reviewer use this version. Principle changes are protected
governance changes requiring human review. Exceptions must include exact scope,
human owner, rationale and expiry; there are no agent-authorized exceptions.

## Review dashboard

Visit `/development-agent` from the Investment Dashboard. Set `DEV_AGENT_API_TOKEN`
through existing server configuration; it is never embedded in HTML. Enter it in the
password field for authenticated reads/decisions. `DEVELOPMENT_CONTROL_DB` may select
the dedicated ledger. Decisions require a same-origin JSON request, token and a
single-use nonce; they grant no merge/deploy authority. Risk and failed-gate warnings
remain visible on mobile. Evidence is text-rendered; external links are restricted
to HTTPS GitHub. Physical iPhone/Android acceptance remains open until observed.

## Scheduling, outcomes and certification

The provided systemd units run daily discovery at 08:15 America/New_York, DST-safe,
with slot idempotency, process locking, bounded backlog and no build invocation.
They are shipped disabled and must not be installed/enabled by development runs.
Transient failures release the lock; a failed unrecorded slot can be retried manually.
Do not perform automatic unbounded retries. Operator pre-creates the private state
directory before enabling the unit under a separate deployment authorization.

Deployment observations are append-only and bind the reviewed PR/merge SHA and
observed deployed SHA. Missing telemetry, mismatched SHA or inadequate observation
window means INSUFFICIENT_DATA. Software effectiveness measures acceptance, recurrence,
review findings, operational health, user acceptance and maintenance; it never uses
investment P&L or changes risk/approval thresholds. Critical receipts remain forever;
transient operator logs expire after 14 days. Downstream UI is read-only except
explicit approval operations. No outcome collector can deploy.

`canary` exercises isolated fixture planning/build/review and authority attacks.
Its result remains PARTIAL until real OS validation, effective GitHub protection
and authenticated production-snapshot checks pass. `certify` performs technical
checks only; it does not record a supervised operational success. The current
hash, three real operational successes spanning seven calendar days, and explicit
autonomy configuration are separate requirements. See the hardening contract below.

## Hardening contract — TODOs 0785–0794

The canonical manifest is `development-validation-2`: focused tests, full suite,
exact release-baseline, CC behavioral contract, agent contract, TODO consistency
and development-governance checks. `validate --image IMAGE@sha256:DIGEST
--review-model MODEL --candidate ID` executes every gate through the application-owned
networkless sandbox. Each result is immediately ledger-persisted with candidate,
TODO, base/head SHA, complete source hash, command version, image digest, timestamps,
exit code and JUnit inventory. Every batch must be complete and current. Model stdout,
zero exit without passing JUnit, or caller-supplied PASS JSON cannot seal evidence.
`seal --candidate ID` accepts no validation/provider payload. Independent review is
refreshed using the complete trusted gate inventory before sealing.

Snapshot certification now requires an authenticated `production-backup-provenance-1`
receipt and matching isolated `.db`. An operator provisions `DEV_AGENT_BACKUP_SIGNING_KEY`
through the existing environment configuration on the backup/verifier processes;
the Builder receives neither that key nor host environment variables. When configured,
the established backup script invokes the OptiPlex-only signer after its online backup.
Without signer configuration the existing backup path is unchanged. An unavailable
verifier means UNAVAILABLE. Never send a signing key in CLI JSON or commit it.
Copy the closed backup and its receipt out of runtime paths before certification.
HMAC authenticates the trusted backup mechanism, source, hash, canonical schema,
migration fingerprint, integrity result, application SHA and timestamp. Backups older
than 24 hours, future timestamps, WAL/journal companions and schema mismatches fail.
Changing backup signing material requires operator provisioning and is not an agent task.

Execution modes are frozen into plan/approval and recorded in start/run/iteration/
receipt/PR lineage. SUPERVISED requires authenticated explicit human invocation,
current technical certification, exact approved base/scope and effective GitHub
protection. It does not require accrued autonomous history. AUTONOMOUS additionally
requires enabled configuration, three real qualifying pilots over seven calendar days,
a current hash, a risk ceiling of L2 and a bounded daily admission reservation.
L3 remains human-started; L4/L5 cannot enter the generic Builder in either mode.
`autonomous_implementation=false`, `emergency_stop=true`, or
`DEV_AGENT_KILL_SWITCH=1` denies autonomous starts. No mode grants merge/deployment
or GitHub configuration authority; `auto_merge` remains false.

Technical `harness-canary-2` receipts are distinct from operational supervision.
An arbitrary actor string cannot create either an authenticated human decision or a
qualifying success. Interactive CLI identity comes from the authenticated OS account;
dashboard identity comes from server-side token/origin verification, not request JSON.
Only complete real Builder/independent Reviewer/validation/seal/verified PR/human
review/deployment-observation lineage counts, once per run and only for the current
harness hash. See [prospective pilots](development-agent-pilots.md).

GitHub handoff checks head repository, branch, exact head SHA, protected main base
and actual draft state after creation/update. Later dispositions recheck identity.
A stale remote head needs new validation, review and a new receipt; the agent never
force-pushes or edits evidence to match it. Effective protection combines classic
branch protections with all active branch rules, including inherited rulesets.
Missing bypass visibility is UNAVAILABLE. Active bypass actors or administrative
agent authority stop promotion. Fresh independent last-push review, stale dismissal,
strict current-head CI, conversation resolution and force/delete protection are
mandatory; repository role names alone never establish effective permission.

The dashboard computes readiness from configuration and immutable certificates/run
history. It shows exact blockers, hash staleness, sandbox/snapshot/protection status,
supervised counts/dates, observation period, disabled autonomy and auto-merge. It does
not infer installed scheduler status: discovery units remain operator-managed and
installation is explicitly unavailable until observed. No dashboard read mutates state.

`autonomous-cycle --candidate ID` progresses only an already frozen, human-approved
AUTONOMOUS L0–L2 scope. It never approves its own discovery/plan proposals. All admission
gates are checked before Builder, again before commit/validation, and before publishing
the exact sealed SHA to the configured repository's agent branch. It runs mandatory
validation and independent review, then verifies remote PR identity. Each validation
command has a bounded timeout and the complete batch is bounded to 40 minutes.
Automatic policy approval of newly discovered candidates is deliberately unavailable;
this phase consumes the explicit approved queue and cannot expand its scope.

The validation container receives a source-only copy and a fresh isolated Git repository,
never host Git configuration, hooks, credentials or historical data blobs. The CC gate
uses its existing `--trusted-prior-file` interface with the baseline extracted by the
trusted host harness from the exact approved base SHA and mounted read-only separately.
The command receipt still binds that immutable base and exact source/head identity.
Financial definition migrations remain outside the generic Builder's authority; no CC
gate implementation, version, baseline or threshold is altered for this validation path.
