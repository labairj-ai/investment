# TODO 0851 — Live-Certify the Bounded L0 Validator

- **ID:** 0851
- **Status:** done
- **Priority:** critical
- **Risk:** L5 — validation trust boundary
- **Parent:** 0847
- **Depends:** merged PR #14 source foundation
- **Blocks:** 0853

## Objective

Install and prove the already-designed bounded L0 validator on the actual model/application host without expanding its scope.

This is an operational acceptance task, not a new validator-design task.

## Required scope

Support only the current approved L0 surfaces:

- Markdown documentation;
- plain text;
- explicitly approved static documentation metadata.

Continue to reject executable code, active HTML, application logic, financial logic, authentication, deployment code and governance changes.

## Installation acceptance

- [x] Install reviewed validator outside all candidate worktrees.
- [x] Use the dedicated validator service identity.
- [x] Validator source is root/operator controlled and nonwritable by Builder.
- [x] Private Unix socket permissions verified.
- [x] Signing material permissions verified.
- [x] Protected Git authority store is nonwritable by candidate/Builder.
- [x] Network access denied.
- [x] Docker socket access denied.
- [x] Production investment DB access denied.
- [x] SSH/user credential access denied.
- [x] Service starts cleanly and reports healthy.
- [x] No existing Qwen/MLX or investment services are changed.

## Live adversarial acceptance

Exercise the installed service against:

- [x] valid L0 document edit;
- [x] active-markup injection;
- [x] executable-file change;
- [x] trusted-test deletion;
- [x] trusted-test rewrite;
- [x] fake PASS artifact;
- [x] fake JUnit artifact;
- [x] symlink substitution;
- [x] timeout;
- [x] crash;
- [x] duplicate/truncated result inventory;
- [x] runtime binary mismatch;
- [x] validator-source mismatch;
- [x] key/socket permission attack;
- [x] candidate socket/key access attempt;
- [x] network access attempt;
- [x] production DB access attempt.

Every unsupported/hostile case must fail closed.

## Required evidence

Preserve a sanitized live acceptance receipt containing:

- exact application SHA;
- validator source digest;
- runtime identity;
- service identity;
- test matrix and results;
- created/observed timestamps;
- scope = L0 static only;
- fixture_only = false;
- no secrets or production data.

## Owner-facing result

Expose only:

L0 Validator: READY

or

L0 Validator: NOT READY — <plain-English reason>

Detailed evidence remains diagnostic.

## Guardrails

- Do not add L1/L2 support.
- Do not enable Builder execution.
- Do not enable supervised loop.
- Do not enable autonomous implementation.
- Do not change investment logic or state.
- Do not deploy any model.
- Do not alter existing MLX services.

## QA

Run focused Development Agent tests, full repository tests, TODO consistency, Development Agent governance and all existing release gates after any source/config changes needed for host installation support.

## Done when

The installed live L0 validator is independently verified READY and 0847 can be closed on real evidence.

## PR #15 source progress

Pinned first-install tooling and a live functional probe are implemented. Stale socket restart now preserves live listeners and refuses unsafe paths. Installation, OS denial matrix and sanitized real acceptance receipt remain outstanding; a functional probe explicitly does not certify the host.

No live acceptance is claimed. All operational checkboxes remain open. See
[the rollout guide](../../docs/development-agent-pr15-rollout.md) for internal prerequisites.

### PR #15 operational usability follow-up

The fixed installed live matrix, automatic off-identity denial probe and sanitized receipt producer are now implemented. These have only been tested in isolated source fixtures; reviewed host installation and actual acceptance remain outstanding.

## Actual OptiPlex acceptance — 2026-10-24

The reviewed production release `05d6cccf734d4604d1a8c10406d9e3d7598e9c6f`
was installed using PR15's unchanged installer. The installed oracle service is
active as investment-oracle; its real acceptance unit exited successfully with
22/22 PASS. The host receipt has fixture_only=false, L0_STATIC_TEXT scope, exact
source/runtime identities and all authority grants false. This supersedes the
older source-only progress notes above; those notes describe historical state.

See [live evidence](../../docs/evidence/l0-live-20261024/README.md), including
actual loaded sandbox/permissions and protected-state observations. No model or
investment service was changed/restarted. The legacy deployment configuration
fingerprint false alarm is retained and diagnosed separately; persistent unit/
drop-in contents, private environment and service process remained unchanged.
The fingerprint fix is proposed only, not installed or deployed.

L0 Validator: READY. This is static host acceptance, not independent pytest
authority, activation or completion of 0852/0853/0854.
