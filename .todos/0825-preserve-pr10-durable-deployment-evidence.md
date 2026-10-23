# TODO 0825 — Preserve PR #10 Durable Deployment Evidence

- **ID:** 0825
- **Status:** in-progress
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

- [ ] Review the existing PR #10 deployment receipt.
- [ ] Remove or redact:
  - local secrets;
  - credentials;
  - private API tokens;
  - private filesystem details not required for validation;
  - production data contents.
- [ ] Preserve:
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
- [ ] Store sanitized receipt under:
  `docs/evidence/continuous-improvement-20261023/deployment-pr10.json`
- [ ] Add a SHA256 digest of the receipt.
- [ ] Add receipt schema/version.
- [ ] Ensure future deployment receipts use the same schema.
- [ ] Add a test validating required deployment-receipt fields.
- [ ] Reject malformed or incomplete receipts from supervised-success evidence.

## Required acceptance

- [ ] Repository copy contains no secret material.
- [ ] Receipt identifies `15df8960b7c376da8b15fd80dad1bfb19aaede9b`.
- [ ] GitHub `main` equals deployed SHA at receipt time.
- [ ] Post-merge CI `39997737221` is recorded as PASS.
- [ ] Runtime health evidence is represented.
- [ ] Mutation-safety result is represented.
- [ ] Receipt hash is reproducible.
- [ ] Evidence consumer rejects manually edited receipt without corresponding hash change.

## Guardrails

- Do not commit production DB contents.
- Do not commit holdings contents.
- Do not commit tokens or SSH material.
- Do not fabricate missing deployment observations.
- Deployment receipt is evidence only; it grants no future deployment authority.

## Done when

- [ ] Sanitized receipt is committed.
- [ ] Receipt-schema test passes.
- [ ] Exact-head CI remains green.

## Implementation / acceptance handoff — 2026-10-23

Implemented schema, canonical and file hashes, authentic sanitized PR10 evidence, consumer rejection and regression checks. The manual release is explicitly excluded from Deployment Agent pilot qualification. Pending exact-head CI and repository merge.

See [live operational acceptance](../docs/live-operational-acceptance.md) and the [sanitized live preflight](../docs/evidence/continuous-improvement-20261023/live-acceptance-preflight.json). This task remains in progress until every required live acceptance and release gate is satisfied.
