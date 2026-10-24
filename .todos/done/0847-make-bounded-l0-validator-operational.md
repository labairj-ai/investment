# TODO 0847 — Make the Bounded L0 Validator Operational

- **ID:** 0847
- **Status:** done
- **Priority:** critical
- **Risk:** L5 — validation trust boundary
- **Depends:** PR #14 bounded static oracle implementation
- **Blocks:** 0849
- **Supersedes:** 0836 and 0837 for the initial rollout

## Objective

Finish and install only the bounded L0 static validator needed for the first useful workflow. Do not build a universal hostile-code validation platform.

## Supported scope

Permit only clearly non-executable L0 work such as Markdown documentation, plain text and approved static documentation metadata.

Reject Python, JavaScript/TypeScript, active HTML, executable configuration, authentication, application logic, financial logic, deployment logic and governance changes. Unsupported work remains supervised/manual.

## Installation

- [x] Install reviewed validator outside candidate worktrees.
- [x] Dedicated service identity.
- [x] Private Unix socket and signing material.
- [x] Protected Git authority store.
- [x] Network disabled.
- [x] Docker socket denied.
- [x] Production DB denied.
- [x] SSH/user credentials denied.

## Live acceptance

- [x] valid static document change;
- [x] active markup rejection;
- [x] executable candidate rejection;
- [x] trusted-test deletion/rewrite rejection;
- [x] fake PASS/JUnit rejection;
- [x] symlink rejection;
- [x] timeout and crash;
- [x] duplicate/truncated result;
- [x] runtime binary mismatch;
- [x] validator-source mismatch;
- [x] key/socket permission attack;
- [x] candidate socket/key access denial;
- [x] network denial;
- [x] production DB denial.

## Owner-facing health

Expose only L0 validator: READY / NOT READY.

## Guardrails

Static PASS never replaces full repository CI and never authorizes executable code. Do not claim L1/L2 support. Do not enable autonomous implementation.

## Done when

A real non-fixture L0 validator is installed, healthy and usable for the first low-risk pilot.

## PR #14 source progress (simplified workflow)

One exact-head owner Go is the authority for merge and downstream deployment;
No-Go/stale-head and all technical gates remain fail-closed. No service is installed,
no live owner decision is created, and all activation flags remain disabled.
See `docs/solo-owner-governance.md` for the active workflow. Source tests are not
live acceptance. This TODO remains open until all its acceptance evidence exists.

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
