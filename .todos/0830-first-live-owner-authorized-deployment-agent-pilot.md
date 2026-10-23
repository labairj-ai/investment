# TODO 0830 — Execute First Live Owner-Authorized Deployment-Agent Pilot

- **ID:** 0830
- **Status:** in-progress
- **Priority:** critical strategic
- **Risk:** L5 — production deployment
- **Depends:** 0827, 0829
- **Blocks:** 0831

## Problem

PR #10 was manually deployed and verified, but the newly implemented Deployment Agent itself has not completed a live production deployment.

This must be proven before deployment can be considered part of the normal continual-improvement pipeline.

## Installation

Install the Deployment Agent controller outside the writable production checkout.

Provision:

- [ ] fixed controller configuration;
- [ ] deployment receipt directory;
- [ ] deployment control ledger;
- [ ] read-only GitHub identity;
- [ ] narrowly scoped service control;
- [ ] observation signing key;
- [ ] observation export directory;
- [ ] deployment poller timer;
- [ ] deployment observer timer.

## Security boundary

Deployment identity may:

- read GitHub metadata;
- fetch `main`;
- checkout exact approved SHA;
- start/stop/restart `investment.service`;
- run fixed health/canary commands;
- write deployment receipts.

Deployment identity may not:

- approve PRs;
- merge PRs;
- push code;
- write branches;
- modify GitHub rulesets;
- receive arbitrary shell commands;
- invoke broker actions;
- alter production investment data.

## Pilot

Use the low-risk merged PR from 0829.

Required flow:

1. [ ] exact owner review exists;
2. [ ] PR merged by owner;
3. [ ] post-merge `main` CI PASS;
4. [ ] owner explicitly authorizes deployment;
5. [ ] ChatGPT connector creates valid `OWNER-DEPLOY deployment-1`;
6. [ ] poller detects authorization;
7. [ ] admission verifies owner/head/merge/CI/main ancestry;
8. [ ] preflight verifies current production;
9. [ ] rollback backup created;
10. [ ] protected-state hashes recorded;
11. [ ] exact merge SHA checked out;
12. [ ] service restarted;
13. [ ] service active;
14. [ ] both dashboards healthy;
15. [ ] authenticated API returns expected success;
16. [ ] unauthorized API returns 403;
17. [ ] Advisor functional canary passes;
18. [ ] mutation-safety canary passes;
19. [ ] holdings unchanged;
20. [ ] investment state unchanged;
21. [ ] Development Agent ledger only contains allowed append-only changes;
22. [ ] durable `DEPLOYED_VERIFIED` receipt created;
23. [ ] delayed observer produces signed HEALTHY observation.

## Failure matrix

Exercise safely through fixture/staged failure injection:

- dirty worktree;
- missing CI;
- stale owner authorization;
- wrong SHA;
- backup failure;
- service-start failure;
- dashboard failure;
- API failure;
- canary failure;
- holdings mutation detection;
- interrupted deployment;
- expired deployment authorization.

No failure may produce `DEPLOYED_VERIFIED`.

## Rollback

- [ ] failed health causes code rollback;
- [ ] prior SHA restored;
- [ ] service restarted;
- [ ] health rechecked;
- [ ] financial database is never rolled back by code rollback;
- [ ] rollback result recorded.

## Done when

- [ ] One real low-risk release is deployed entirely through Deployment Agent.
- [ ] No manual SSH deployment commands are needed.
- [ ] Durable receipt exists.
- [ ] Signed post-deployment observation is HEALTHY.

## Implementation / acceptance handoff — 2026-10-23

Corrected fixed health endpoints, added complete investment-state identity and standard receipt export, and revalidated owner/main/CI before successful completion. Dedicated installation, permission proof, failure matrix and real pilot remain pending.

See [live operational acceptance](../docs/live-operational-acceptance.md) and the [sanitized live preflight](../docs/evidence/continuous-improvement-20261023/live-acceptance-preflight.json). This task remains in progress until every required live acceptance and release gate is satisfied.
