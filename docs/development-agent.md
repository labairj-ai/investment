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

`canary` exercises isolated fixture planning/build/review/evidence and adversarial
guards. Its result remains PARTIAL until actual OS validation, GitHub identity/
protection, read-only production-snapshot checks and supervised observation pass.
`certify --image IMAGE@sha256:DIGEST --input supervised.json` performs one explicit
supervised run. Input names the isolated snapshot and supervising human actor; the
tool executes the OS-sandbox test and GitHub verification itself. It never converts
a fixture PASS into an operational PASS. `current` independently enforces the
required count and elapsed period across distinct, current-hash supervised receipts.
Autonomous implementation is disabled by configuration. Enabling it requires a
reviewed change, three supervised successful certifications under identical harness
hashes spanning at least seven days. Changes to harness/config/contract invalidate
prior certificates. Certification never authorizes financial/execution autonomy.
