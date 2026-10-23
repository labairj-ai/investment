# Continuous improvement: authority and operator acceptance

This implementation reconciles 0816–0824 on base main `3b497914270fe53beaecba9c8d2fdd0b80f427fe`. Every task remains in-progress until its complete live acceptance passes. No implementation flag, timer, owner approval, protection rule or deployment is activated by building the code.

## Authority flow

A read-only collector produces bounded operational metadata. Networkless Scout discovers/deduplicates candidates. A separately authenticated owner build policy may delegate frozen L0–L2 scope to the supervised loop. The structured Builder cannot execute shell commands, modify requirements/governance/deployment code or choose host operations. An independent Reviewer and mandatory exact-head validation precede publication. A published PR grants no merge or deployment authority.

ChatGPT may recommend OK/NO after inspecting the real diff and current CI. The recommendation is not approval. Only the owner's subsequent deliberate decision authorizes the owner-side gateway. The gateway is installed on the owner/connector side, with credentials inaccessible to the agent. It checks GitHub's authenticated user ID/login, posts the exact structured decision, and optionally performs an immediate expected-head merge only when the current human workflow explicitly authorizes it. It does not enable GitHub auto-merge or authorize deployment. The agent has read-only ingestion of the resulting GitHub object.

Deployment has a different actor, credential set, authorization object and fixed command set. It consumes only an owner-approved merged main SHA. It cannot approve PRs, write branches, change rulesets or receive arbitrary model-generated shell commands. No production database contents enter model context. Autonomy may eventually progress only to PR creation; owner approval and deployment authorization remain separate.

## Implementation and open acceptance

| TODO | Implemented | Still required before closure |
|---|---|---|
| 0816 | Owner attestation, CLI/API/dashboard, immutable owner event, actual owner merge actor, hardened identity and complete protection lifecycle reconciled | Full green release evidence and owner acceptance |
| 0817 | Independent gate execution, exact-head summary, JUnit/counts and aggregate failure/artifacts | Current simulator contract reconciliation and exact-head green CI |
| 0818 | Host-private immutable collector, signed independent-oracle protocol, expected inventory and source/image/run bindings; candidate diagnostics cannot grant PASS | Approved separately isolated oracle implementation, pinned runtime and real adversarial containment matrix |
| 0819 | Owner-side action gateway; structured owner ID/login verified GitHub ingestion, nonce/head/risk/acks, fresh revocation and atomic expected-head merge | Owner-side installation and real OK/NO/concurrent-push test PR acceptance |
| 0820 | Discovery/observer units, read-only systemd observation, durable timings and stale health projection | Reviewed installation and three actual scheduled daily executions |
| 0821 | Bounded CI/systemd/loopback collector, typed runtime/performance/accessibility adapters, private spool, redaction and recurring identity; explicit owner feedback | Enable real collectors, establish trend/UX/log input sources and observe production-derived candidates; unsupported collectors stay unavailable |
| 0822 | Frozen plan/worktree, explicit owner build delegation, bounded real Runner/Reviewer/validation, phase machine and PR notification; three synthetic L0/L1/L2 journeys tested | Real owner delegation, independent validation runtime and three complete prospective supervised journeys |
| 0823 | Exact merge/head/owner/CI admission, fixed local executor, backup, health/canaries, protected-state checks, immutable receipts and code rollback/recovery | Dedicated read-only GitHub/deployment identity, operator-installed controller, safe ledger access and actual deployment/failure matrix |
| 0824 | Shadow/build-only/PR controls, caps, fresh evidence, pause and operator review, source-bound stage observations | Three real supervised successes over at least seven calendar days, current technical/deployment certificates, completed prior tasks and separate owner-approved activation change |

The generic pytest interpreter can be modified by imported candidate Python. A host-side XML writer alone cannot turn its claims into independent PASS evidence. See [artifact boundary](development-agent-artifact-integrity.md). The current validator returns UNAVAILABLE without an independently isolated oracle; fixtures are not an implementation of that oracle. Do not install a service that merely signs the candidate's own reported test results.

Repository GitHub CI is deliberately labeled repository diagnostics, not an agent technical certificate. It executes all independent gates and fails on any mandatory failure. The contained agent validator remains a separate mandatory admission path; repository CI cannot replace it.

## Owner OK/NO payload

The owner-side gateway creates a PR comment whose body is exactly this header followed by a JSON object, without prose/code fences:

```
OWNER-REVIEW solo-owner-2
{"repository":"labairj-ai/investment","pr":123,"head":"EXACT_40_HEX_SHA","risk":"L0","decision":"APPROVE","nonce":"UNIQUE-SINGLE-USE-NONCE","rationale":"Owner reviewed the actual diff and CI","financial_ack":false,"execution_ack":false}
```

Decisions are APPROVE, REQUEST_CHANGES and DEFER. Present the exact head, risk and required domain acknowledgment to the owner before asking OK/NO. L3+ approval needs rationale; L4 needs financial acknowledgment; L5 conservatively needs both acknowledgments. Never infer those from model advice. No conversation transcript or OAuth token is sent to the agent. Objects must be unedited, at most 24 hours old and authored by the configured personal owner ID/login, not an app/bot/service account. Ambiguous JSON, wrong repository/PR/head/risk, missing acknowledgments or incomplete decision visibility fail closed.

The agent operator can ingest an object read-only with `python -m dev_agent.cli owner-ingest --input object.json`, where object.json contains `{"object_id":123}`. Latest structured owner decisions are rechecked on GitHub before reusing approval: a newer NO immediately invalidates an older GitHub OK even before local ingestion. Changed head invalidates every source's review. Nonces cannot be reused for another origin/context. An owner-side immediate merge supplies GitHub's atomic expected SHA; a concurrent push is rejected. A later NO blocks subsequent deployment admission. Never run the owner gateway using an agent credential or in the Builder service.

## Operator setup (not executed by this change)

1. Review/merge the implementation through the owner-controlled workflow. Deploy the exact merged main SHA only after every release gate passes; preserve rollback and financial state. Do not deploy an unmerged feature head.
2. Provision owner bindings outside source, using the verified owner ID/login. Tailscale mutations require the existing unique operator allowlist, trusted Serve headers and loopback-only listener. Shared token or request-body actor is insufficient. Keep the owner gateway credential on the owner side and a separate non-admin non-bypass credential on the agent host.
3. Provision the digest-pinned validator image out-of-band. Keep `--pull=never`, no network, read-only source, no secrets/socket, non-root, capability drop and bounded resources. Provision and review the separate oracle adapter and host-private key/socket. `DEV_AGENT_ORACLE_SOCKET` and `DEV_AGENT_ORACLE_KEY_FILE` are never passed to candidate containers. Full signed oracle receipts are stored outside candidate mounts; validation binds them to a unique run, source/oracle trees, approved base, head and image digest.
4. Install the reviewed discovery service/timer and read-only scheduler observer as user units. Initialize the dedicated development ledger first. Retain PrivateNetwork, NoNewPrivileges and narrow writable development paths. Observe three genuine daily runs at 08:15 America/New_York; do not backdate or substitute manual runs. Scheduler health expires after an hour without observation and a scheduled scout is stale after 36 hours without success.
5. Install the separate read-only metadata collector if approved. Only it needs GitHub/loopback access. It writes an atomic mode-0600 operational-signals.json; discovery.env names that path in DEVELOPMENT_SIGNAL_SPOOL. Scout remains networkless. Enable additional performance/log/UX input adapters explicitly; an unavailable signal is not a healthy measurement. Never retain raw private logs or transmit private operational data to an unapproved external model.
6. On a dedicated validation checkout outside production, deliberately authorize an expiring L0–L2 build policy with `approve-build-policy`, exact allowed patterns, nonce and rationale. The policy is a BUILD_POLICY event, not an owner PR approval. Keep supervised_loop_enabled=false until runtime/protection gates pass. Begin with supervised_publish_pr=false for build-only acceptance; a separate reviewed setting permits supervised PR publication. Units run only the fixed supervised-cycle entry point, never merge/deploy. Preserve all failed attempts for review.
7. Install the deployment controller from an approved pinned version outside the writable production checkout. Its root-owned /etc/investment-deploy/config.json provides exact repository/root/receipt/ledger/origin and emergency-stop settings. A distinct investment-deploy identity receives only read GitHub permissions and fixed investment.service start/stop/restart via the reviewed polkit rule. It must not receive manage-unit-files, general sudo, push, ruleset or owner credentials. Provision read-only authority-ledger access and the narrowly scoped private local API credential. Installation/permission compatibility must be proven, not inferred from the unit template. The controller currently refuses autonomy-bit changes; activation uses the separate reviewed governance deployment path.
8. Do not install/start the supervised loop or deployment service merely because unit tests pass. Their real acceptance receipts must demonstrate all entry and failure paths. No generic self-hosted runner should execute arbitrary repository jobs on OptiPlex; use the fixed installed service.

A separate owner-authored deployment comment uses `OWNER-DEPLOY deployment-1` followed by JSON with repository, PR, head, merge_sha, nonce, expires_at (Unix seconds within 24 hours), rationale and execution_ack=true. Deployment admission requires the current owner review, exact head and merged-main CI, real owner merge actor, ancestry and emergency-stop clearance. Run the fixed installed service with its integer authorization object ID. There is no arbitrary target/shell parameter. It retains backups and rollback receipts; failed checks prevent DEPLOYED_VERIFIED. Interrupted deployment requires explicit fixed recovery; database rollback is prohibited. New unit/timer installation is outside this initial fixed transaction and requires a separately reviewed operator rollout.

## Stage evidence and activation

Structural harness identity includes code, tests, contracts, workflow and safety configuration. Exactly four activation-only fields are normalized to their disabled/shadow values: autonomous_implementation, autonomy_stage, supervised_loop_enabled and supervised_publish_pr. This deliberate fixed rule prevents the enable bit from invalidating the prospective evidence needed to enable it. The normalizer cannot be configured by a model. Risk ceiling, budgets, TTLs, authority flags, images and all other safety configuration remain bound. Any implementation/safety change invalidates certification. Runtime policy and exact PR SHA remain independently visible and owner-reviewed; the normalizer grants no activation authority.

Actual shadow cycles and distinct build-only validations are recorded under the current structural harness. Replay providers/fixtures never count as stage or operational success. Stage B never publishes its build-only candidate. Supervised PR journeys are separate from autonomous Stage C. A separate activation PR must preserve L2 maximum, one daily start initially (hard limit three), human merge and deployment controls. New starts stop for stale certificates, snapshot or protections, kill switch, repeated failures or abnormal deployment; owner pause review does not itself enable autonomy.

No software or investment P&L metric is used as a substitute for real software outcomes. No task is closed on fixture evidence.

## Runtime handoff details

The deployment poller reads bounded owner-authored authorization objects through outbound GitHub API calls and invokes only the installed fixed deployment entry point. It is not a general self-hosted Actions runner. Deployment authority is mirrored into a separate private control ledger; the development ledger remains read-only to admission. Full backup/deployment receipts stay private. The observer exports only signed software metadata for the supervised loop to verify and ingest. A degraded outcome pauses progression; a healthy outcome still requires the complete owner/protection/validation lifecycle before qualifying.

Scout receipts distinguish manually invoked runs from observed systemd timer runs using the actual service invocation ID, PID and recent timer trigger. Duplicate runs remain auditable but do not manufacture additional daily observation slots. None of these services or timers has been installed or activated by this implementation.
