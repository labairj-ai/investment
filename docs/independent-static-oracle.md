# Independent bounded validation backend (0836–0837)

The initial backend is **L0 static document text only**. `ops/validator/static_oracle.py` is a standalone standard-library program installed outside candidate worktrees. It never imports candidate modules, pytest, plugins, conftest, sitecustomize or candidate configuration. A fixed controller-owned Git object store, approved base and repository define authority. Operator-reviewed user-document prefixes (for example `docs/help/`) bound eligible changes; governance, tests, executable code, active HTML, deletions, executable file modes, symlinks and submodules are rejected. No existing application-validation gate is relaxed.

The trusted inventory consists of four fixed static rules, not pytest test IDs. It binds the complete candidate tree, approved-base trusted test tree, static rule inventory, exact base/head/repository, command class, trusted validator source digest and independently checked Python executable digest. A separate `python -I -S` child receives text as JSON data. The parent observes exit/timeout itself, validates the exact results inventory and signs the receipt using a key outside candidate access. A crashed/timed-out/truncated/duplicate-result child cannot produce PASS. Candidate artifact files are neither read nor signed.

The distinct `bounded-static-oracle-1` protocol **cannot** be passed to `isolated-oracle-1` or substitute for pytest, the mandatory repository gates, a technical certificate, live certification or Builder admission. L1 executable tests/tooling and L2 browser validation remain unavailable pending independently designed/reviewed backends. This implements a deliberately bounded first backend; 0836's review and broader class coverage remain open.

## Provisioning after exact-head owner review

Use a dedicated `investment-oracle` service identity. Install the reviewed source root-owned and nonwritable at `/opt/investment-static-oracle/static_oracle.py`. Provision a controller-owned bare Git object store at `/var/lib/investment-static-oracle/authority.git`; no candidate principal may write that store, its configuration, objects, refs or any ancestor. Import candidate objects through a separately reviewed fetch-only controller with no candidate Git hooks, filters, submodule traversal or credentials inherited by the validator. Do not expose a writable candidate checkout as authority.

Install `ops/validator/investment-static-oracle.service` after checking host systemd compatibility. The template disables networking, home access, Docker sockets, capabilities and privileged operations, and limits resources. The supervisor may invoke the private client as the oracle identity; Builder must run as a different identity with no socket or key access. No arbitrary RPC command is accepted. Do not grant the Builder membership/access to the oracle identity or directory.

Provision `/etc/investment-static-oracle/config.json` and the signing key as private 0600 files readable by the service identity; the configuration directory must resist candidate writes and the service mount makes configuration read-only. Use at least 32 random key bytes, never put key bytes into source, logs, request JSON or certificates. The private `/run/investment-static-oracle` directory is created by systemd with mode 0700. Example non-secret configuration shape:

```json
{
  "repository": "labairj-ai/investment",
  "approved_base": "REVIEWED_FULL_BASE_SHA",
  "authority_git_dir": "/var/lib/investment-static-oracle/authority.git",
  "allowed_prefixes": ["docs/help/"],
  "runtime_identity": "python@sha256:ACTUAL_PINNED_PYTHON_EXECUTABLE_SHA256",
  "signing_key": "/etc/investment-static-oracle/signing.key",
  "socket": "/run/investment-static-oracle/oracle.sock"
}
```

The actual Python executable hash is independently recomputed on every request. A changed interpreter fails closed. The validator source digest must match the reviewed installation and the supervisor's expected digest. Upgrades require renewed owner review and live certification. A private current-base config is never accepted from candidate request JSON.

## Live certification still required

No service was installed by this development change. No live certificate exists. After review/provisioning, execute a real passing document candidate and a known failing active-markup candidate; execute every 0836 adversarial attempt against the installed endpoint, confirming rejection of unsupported executable surfaces before any execution. Also stage timeout/crash recovery, check host-source/config integrity and verify no residual child/socket/container. Observe actual UID, network, credential, key, production DB and Docker access denial with the candidate service identity. Unit tests do not prove those OS boundaries.

Preserve a non-fixture certificate with harness hash, backend/protocol/source/runtime identities, creation/expiry, exact static inventory and candidate matrix, process/timeout observations and artifact-integrity PASS. It must explicitly state `scope=L0_STATIC_TEXT`, `grants_pytest_authority=false`. It must never be relabeled as the general executable oracle certificate consumed by current supervised admission. Until a supported reviewed backend is integrated into that admission and certified, 0837/0826 and the supervised Builder remain blocked.

## Simplified rollout adapter (0847)

The trusted supervisor's `static_validation.installed` uses its private configured
socket/key and pinned runtime/source identities. L0 mandatory validation records
an exact-base/head static receipt before the full test gates; sealing requires that
receipt. It never replaces independent test-result integrity or repository CI.
Missing installation stays unavailable. `DEV_AGENT_STATIC_ORACLE_SOCKET`,
`DEV_AGENT_STATIC_ORACLE_KEY_FILE`, `DEV_AGENT_STATIC_ORACLE_RUNTIME_IDENTITY` and
`DEV_AGENT_STATIC_ORACLE_SOURCE_SHA256` are supervisor configuration only, never
owner-facing inputs or Builder environment. No L1/L2 backend was added.

The remaining operational integration must demonstrate that the installed bounded
L0 service and mandatory validation path work together on a real candidate. Until
then, the existing independent pytest-result oracle requirement remains fail-closed;
source tests alone neither unblock the first pilot nor certify that boundary.
