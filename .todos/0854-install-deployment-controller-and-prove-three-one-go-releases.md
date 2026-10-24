# TODO 0854 — Install the Deployment Controller and Prove Three One-Go Releases

- **ID:** 0854
- **Status:** backlog
- **Priority:** critical strategic
- **Risk:** L5 — production deployment
- **Parent:** 0850
- **Depends:** 0853
- **Blocks:** future low-risk automatic PR decision

## Objective

Install the bounded Deployment Controller and prove that a single owner Go can safely carry an approved release through deployment after all technical gates pass.

Then complete three genuine supervised releases with no additional owner ceremony.

## Controller installation

- [ ] Install controller outside writable application source.
- [ ] Use dedicated service identity.
- [ ] Restrict GitHub capability to required read/verification operations.
- [ ] Restrict service-control capability to the fixed investment service only.
- [ ] Provision private observation/signing material.
- [ ] Provision private raw receipt storage.
- [ ] Provision sanitized evidence export.
- [ ] Verify controller cannot push.
- [ ] Verify controller cannot merge.
- [ ] Verify controller cannot approve PRs.
- [ ] Verify controller cannot edit GitHub protection/rulesets.
- [ ] Verify controller cannot execute arbitrary shell commands.
- [ ] Verify controller cannot access broker/execution credentials.
- [ ] Verify controller cannot mutate investment data.

## First production pilot

Use the successfully owner-approved release from 0853.

After the owner's existing Go, the system should automatically:

- [ ] verify the exact approved PR head;
- [ ] verify owner approval is still current;
- [ ] verify exact merge SHA;
- [ ] verify merged-main CI PASS;
- [ ] verify current main contains the approved merge;
- [ ] capture pre-deployment protected-state identity;
- [ ] create integrity-checked rollback backups;
- [ ] deploy the exact merge SHA;
- [ ] restart only the fixed application service;
- [ ] verify investment dashboard health;
- [ ] verify Development Agent health/API;
- [ ] verify Advisor functional canary;
- [ ] verify Advisor mutation-safety canary;
- [ ] verify holdings unchanged;
- [ ] verify investment state unchanged;
- [ ] record delayed health observation;
- [ ] preserve durable deployment receipt;
- [ ] report DEPLOYED or FAILED/ROLLED BACK in plain English.

No second owner approval is allowed.

## Failure acceptance

Prove fail-closed behavior for:

- [ ] stale owner approval;
- [ ] wrong PR head;
- [ ] wrong merge SHA;
- [ ] failed merged-main CI;
- [ ] main advanced unexpectedly;
- [ ] dirty deployment source;
- [ ] backup/integrity failure;
- [ ] service restart failure;
- [ ] HTTP/API health failure;
- [ ] Advisor canary failure;
- [ ] protected investment-state mutation;
- [ ] interrupted deployment.

No failed case may produce a successful deployment receipt.

## Three-release evidence

Complete three genuine supervised releases.

For each preserve:

- exact reviewed PR/head;
- owner Go;
- exact merge SHA;
- merged-main CI;
- controller admission;
- deployment receipt;
- post-deploy health;
- rollback outcome if applicable;
- protected-state comparison.

Track aggregate:

- successful releases;
- CI failures;
- Reviewer failures;
- deployment failures;
- rollbacks;
- authority violations;
- investment-state mutations.

## Owner-facing readiness

After three accepted releases, surface:

LOW-RISK AUTO-PR: READY

or

LOW-RISK AUTO-PR: NOT READY — <plain-English reason>

This recommendation concerns only automatic creation of eligible low-risk PRs.

It does not authorize autonomous merge, autonomous deployment, financial logic changes, or expansion beyond the admitted risk level.

## Guardrails

- Human Go remains required before main.
- auto_merge remains false.
- Autonomous deployment remains disabled as an independent authority.
- No financial/execution/governance changes are admitted.
- Kill switch/emergency stop remains effective.
- Deployment never restores the investment DB as part of code rollback.

## QA

Run controller-specific unit/adversarial tests plus the full repository release gates after any installation-support code changes.

## Done when

Three supervised one-Go releases complete successfully with zero authority violations and zero investment-state mutations, and 0850 can be closed on real operational evidence.
