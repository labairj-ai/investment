# Live operational acceptance: 0825–0831

This phase proves operation; it does not equate source deployment or unit tests with certification. The observed OptiPlex baseline is [recorded separately](evidence/continuous-improvement-20261023/live-acceptance-preflight.json). At that observation the application was active at PR10's merge SHA, but Docker, the default oracle socket, the dedicated deployment controller and discovery timer were unavailable. All four activation flags were false. No production database contents or credentials are retained in this evidence.

| TODO | Source/evidence in this change | Remaining live acceptance |
|---|---|---|
| 0825 | Authentic sanitized PR10 receipt, versioned schema, canonical payload digest, file digest, required-field checks and consumer rejection | Exact-head CI and owner review/merge of durable repository evidence |
| 0826 | Preserve fail-closed oracle boundary; expose missing real oracle certificate in promotion report | Implement/review an independent oracle backend, provision isolated runtime/socket/key, clean candidate and full adversarial live matrix, current non-fixture certificate |
| 0827 | Existing connector ID/slug and owner identity checks preserved; new release admission requires observed head/main CI run identities | Real L0 PR, deliberate owner OK and NO, connector objects and read-only ingestion under external owner bindings, stale/replay/domain-ack negative acceptance |
| 0828 | Correct actual HTTP port and 5xx evidence; complete discovery run identity/timing for failures and duplicates | Reviewed unit installation, all requested signal collectors, three actual scheduled slots, protected-state observation and dashboard acceptance |
| 0829 | Existing isolated supervised pipeline and admission remain gated; deployment evidence now mandatory for successful qualification | Prerequisites PASS, separate reviewed supervised activation, real candidate/Builder/Reviewer/oracle/PR/owner journey |
| 0830 | Fixed controller checks actual port and full investment-state identity, exports standard evidence, rechecks owner/main/CI at completion | Dedicated host identity and credential/key provisioning, installed pinned controller and service permissions, first real owner-authorized release, failure matrix and signed delayed observation |
| 0831 | Read-only promotion report with qualifying/nonqualifying runs, failure history, metrics, current harness/configuration, certificate checks and explicit GO/NO-GO | Three real qualifying journeys spanning at least seven New York calendar days, no unresolved incidents, all required current certificates and protection evidence |

## Receipt validation and authority

`deployment-evidence-1` permits only explicit identity, CI, health, state safety, backup integrity and activation fields. It has no arbitrary log/text/credential or private path fields. `sha256` is the SHA256 of canonical JSON containing `schema` and `receipt` without the digest itself. The adjacent `.json.sha256` file contains the SHA256 of the committed file bytes. Both are reproducible:

```bash
venv/bin/python scripts/check_deployment_receipt.py docs/evidence/continuous-improvement-20261023/deployment-pr10.json
```

A digest detects edits; it does not authenticate an operator, authorize deployment or prove that a manually supplied observation is true. Repository history binds the historic PR10 observation to review. Live fixed-controller receipts are created from actual admission, backup, health and protected-state checks, stored immutably and included in the signed software observation. The ledger pins the exact normalized receipt digest. Altered, missing, wrong-PR, wrong-head, wrong-merge, fixture and manual-release evidence cannot qualify supervised success. Legacy successes without the new receipt are nonqualifying; they are not silently grandfathered. Normal append-only development-control changes remain permitted only through the existing allowlist and immutable-prefix checks; investment state and holdings must remain identical.

PR10 was a manual owner-authorized release. Its receipt deliberately uses `actor=manual-owner-authorized`, so it cannot satisfy 0830 or count as one of the three 0831 Deployment Agent journeys. Its backup hash/integrity and health observations are taken from the existing host deployment receipt; no new deployment is fabricated.

## Oracle acceptance prerequisite

The existing `OracleClient` is a protocol boundary, not a working independent oracle backend. Importing candidate Python into the same pytest interpreter lets that code affect pytest reporting. Signing or normalizing those claims in another process cannot establish independent PASS. A host socket server that merely signs candidate JUnit would violate 0818/0826 and must not be installed.

Provisioning requires an approved backend whose assertions and observed outcomes remain independent of candidate Python, a reviewed pinned runtime and an actual live adversarial run. The backend must bind repository, command class, process result, base/head, both tree hashes, expected inventory and image digest. The currently deployed client protocol does not itself establish every one of those live bindings. Until the backend and protocol coverage are implemented, reviewed and certified, artifact integrity remains UNAVAILABLE and real supervised builds must remain disabled. No certificate in this change claims otherwise.

## Owner workflow acceptance

Use the already implemented owner-side gateway and the structured `OWNER-REVIEW solo-owner-2` object. External bindings must preserve approved human operators and explicitly allow app ID 1144995 and slug `chatgpt-codex-connector`; the owner numeric ID/login and User type still determine authority. Do not copy OAuth tokens into the agent host or source.

A real owner must see the exact test PR head/diff/CI before replying OK or NO. Building this backlog is not approval of a future test PR. Owner acknowledgment, application metadata and GitHub merge observations must be obtained from actual GitHub objects. A comment without the versioned payload is not an ingestible protocol acceptance result. Preserve failures and stale heads in the ledger. Exercise deployment authorization against a fixed non-production adapter first. This test does not authorize production deployment or supervised activation.

## Read-only discovery rollout

Install reviewed `development-scout.*`, `development-scheduler-observer.*` and `development-signal-collector.*` units only after their prerequisites and release review. Preserve PrivateNetwork for Scout, NoNewPrivileges and narrow writable paths. The collector is a separate read-only metadata process; no owner credentials or broker authority may be inherited by Scout or Builder.

The current collector implements bounded recent CI failure metadata, service restart state and HTTP observations. A real HTTP 5xx now becomes an observed failure instead of an unavailable source, and the fixed loopback port matches OptiPlex's 5001 service. Log/error, stale-job, accessibility/mobile and performance-trend collectors are not all implemented or live-accepted yet; do not mark them globally available. Explicit user feedback and source TODO/FIXME discovery use existing input paths.

The daily Scout timer runs at 08:15 America/New_York with bounded jitter. Success must be tied to a real systemd invocation/PID and recent timer trigger. Three operator invocations do not establish three scheduled runs, and duplicate daily slots do not advance the evidence window. Record production-state safety outside Scout; never give discovery a production DB handle simply to generate its own safety evidence.

## Deployment controller rollout

The controller remains separate from Scout/Builder/Reviewer. Its current fixed HTTP target is loopback port 5001, matching production. Before stopping the application it validates owner/head/merged-main CI, current main, dirty source, backup and policy. It rechecks authority at completion and requires the same source target, health and protected state. Raw receipts remain private; only the sanitized schema is exported with signed software observations. No generic shell endpoint or arbitrary Actions job is introduced.

Install the pinned controller outside the writable application tree, provision the dedicated read-only GitHub identity and local API credential, fixed service-control permission, private signing key and export directory, then prove permissions using the actual service account. Existing templates alone do not prove that installation works. Stage failure injection before the first low-risk release. Code rollback must never restore the financial database. Successful source tests are not a deployment-agent certificate.

## Prospective promotion report

```bash
venv/bin/python scripts/development_acceptance_report.py --ledger ~/.local/share/investment-development/development-control.sqlite3
```

This command reads the dedicated ledger and source/configuration; it neither installs services nor writes implementation, attestations, certificates or configuration. A NO-GO report exits nonzero and lists missing tasks, current certificates, protection, incidents and the real seven-day/three-run deficit. Its output is also available in the dashboard API's `operational_acceptance` field. Even `GO_FOR_OWNER_STAGE_REVIEW` is a recommendation only. It cannot enable autonomy, merge or deploy.

After qualifying prospective evidence, the first recommendation is an owner-reviewed BUILD_ONLY stage, followed by observed stage acceptance before PR autonomy. Autonomy activation is a separate L5 reviewed change. Keep autonomous implementation, supervised loop, supervised publication and auto-merge false throughout this unreviewed implementation branch. No investment P&L is used in software promotion metrics.
