# TODO 0825 — Preserve PR #10 Durable Deployment Evidence

- **ID:** 0825
- **Status:** done
- **Priority:** high
- **Risk:** L1 — evidence / release history
- **Depends:** PR #10 deployment
- **Blocks:** 0831

## Problem

PR #10 is deployed and verified at:

`15df8960b7c376da8b15fd80dad1bfb19aaede9b`

The deployment receipt currently exists outside the repository working tree.

The Development Agent needs durable, sanitized, immutable deployment evidence so future certification and supervised-success calculations do not depend on a workstation-local file or operator recollection.

## Scope

- [x] Review the existing PR #10 deployment receipt.
- [x] Remove or redact:
  - local secrets;
  - credentials;
  - private API tokens;
  - private filesystem details not required for validation;
  - production data contents.
- [x] Preserve:
  - PR number;
  - approved PR head SHA;
  - merge SHA;
  - deployed SHA;
  - prior deployed SHA;
  - deployment timestamp;
  - exact-head CI run;
  - post-merge CI run;
  - service status;
  - dashboard health;
  - Development Agent dashboard health;
  - authenticated API result;
  - unauthorized API rejection result;
  - Advisor functional canary result;
  - Advisor mutation-safety result;
  - holdings unchanged result;
  - investment-state unchanged result;
  - development-ledger unchanged result;
  - rollback backup existence/integrity result;
  - activation settings after deployment.
- [x] Store sanitized receipt under:
  `docs/evidence/continuous-improvement-20261023/deployment-pr10.json`
- [x] Add a SHA256 digest of the receipt.
- [x] Add receipt schema/version.
- [x] Ensure future deployment receipts use the same schema.
- [x] Add a test validating required deployment-receipt fields.
- [x] Reject malformed or incomplete receipts from supervised-success evidence.

## Required acceptance

- [x] Repository copy contains no secret material.
- [x] Receipt identifies `15df8960b7c376da8b15fd80dad1bfb19aaede9b`.
- [x] GitHub `main` equals deployed SHA at receipt time.
- [x] Post-merge CI `39997737221` is recorded as PASS.
- [x] Runtime health evidence is represented.
- [x] Mutation-safety result is represented.
- [x] Receipt hash is reproducible.
- [x] Evidence consumer rejects manually edited receipt without corresponding hash change.

## Guardrails

- Do not commit production DB contents.
- Do not commit holdings contents.
- Do not commit tokens or SSH material.
- Do not fabricate missing deployment observations.
- Deployment receipt is evidence only; it grants no future deployment authority.

## Done when

- [x] Sanitized receipt is committed.
- [x] Receipt-schema test passes.
- [x] Exact-head CI remains green.

## Implementation / acceptance handoff — 2026-10-23

Implemented schema, canonical and file hashes, authentic sanitized PR10 evidence, consumer rejection and regression checks. The manual release is explicitly excluded from Deployment Agent pilot qualification. Implementation validated locally and in exact-head GitHub CI. Repository promotion remains owner-reviewed.

See [live operational acceptance](../../docs/live-operational-acceptance.md) and the [sanitized live preflight](../../docs/evidence/continuous-improvement-20261023/live-acceptance-preflight.json). All required receipt acceptance and implementation release checks passed. Dependent live operational tasks remain open.

## Validation evidence

- Validated implementation: `cd266a9e6eb2c44ca1a7a374d121df69d879e3ae`.
- [Exact-head CI PASS](https://github.com/labairj-ai/investment/actions/runs/40002223544).
- Complete suite: 2,993 passed, 18 unchanged skips, zero failures; all eight gates PASS.
- Normalized receipt payload SHA256: `9d0ff69b181b9b2a63401816b4d992b17fcb56e32b0d624e5f1f3caa0837eda3`.
- Receipt and file digest are committed in this PR. This closure grants no future deployment, pilot or autonomy authority.
