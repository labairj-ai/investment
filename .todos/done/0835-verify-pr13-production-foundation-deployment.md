# TODO 0835 — Verify PR #13 Production Foundation Deployment

- **ID:** 0835
- **Status:** done
- **Priority:** critical
- **Risk:** L5 — production deployment
- **Depends:** PR #13 merged
- **Blocks:** 0836–0842

## Objective

Complete and preserve production verification for PR #13 merge:
`d12dcf3746dc7266ef4de02f06a48c2b629580e6`.

The GitHub release gates and owner deployment authorization already exist. This task establishes whether the exact code foundation is actually running on OptiPlex.

## Required acceptance

- [x] OptiPlex repository HEAD exactly equals `d12dcf3746dc7266ef4de02f06a48c2b629580e6`.
- [x] Tracked worktree clean.
- [x] `investment.service` active.
- [x] Investment dashboard HTTP 200.
- [x] Development Agent dashboard HTTP 200.
- [x] Authenticated Development Agent API HTTP 200.
- [x] Unauthorized Development Agent API HTTP 403.
- [x] Advisor functional canary PASS.
- [x] Advisor mutation-safety canary PASS.
- [x] Holdings unchanged.
- [x] Investment database state unchanged.
- [x] Development ledger unchanged except explicitly expected release evidence.
- [x] Rollback backup exists and passes integrity verification.
- [x] Activation remains `autonomous_implementation=false`, `supervised_loop_enabled=false`, `supervised_publish_pr=false`, `auto_merge=false`, `autonomy_stage=SHADOW`.
- [x] Preserve sanitized deployment receipt.
- [x] Record exact merge CI run.
- [x] Record exact deployment authorization comment ID.
- [x] Close PR #12 as superseded if still open.

## Guardrails

Deployment of PR #13 is not operational certification of the oracle, Scout, supervised loop or Deployment Agent.

Do not install/activate 0826–0831 runtime components in this task.

## Done when

A durable `DEPLOYED_VERIFIED` foundation receipt exists for `d12dcf37...`.

## Verification evidence

- Production merge: `d12dcf3746dc7266ef4de02f06a48c2b629580e6`.
- [Merged-main CI run 40026606075](https://github.com/labairj-ai/investment/actions/runs/40026606075): SUCCESS.
- [Owner deployment authorization comment 6375211303](https://github.com/labairj-ai/investment/pull/13#issuecomment-6375211303): exact head/merge; owner User 260142791 / labairj-ai; connector 1144995 / chatgpt-codex-connector; unedited object.
- [Sanitized durable DEPLOYED_VERIFIED receipt](../../docs/evidence/pr13-foundation-20261023/deployment.json), adjacent file SHA256, and [read-only current verification](../../docs/evidence/pr13-foundation-20261023/current-verification.json).
- Original host receipt and integrity-checked rollback backups: `/home/optiplex/.local/share/investment-releases/pr13-20261023T215941Z/` on OptiPlex. No production data was copied into development.
- Holdings, investment-state and development-ledger identities matched before/after deployment. Advisor functional and mutation-safety canaries PASS. Current service/HTTP/API/SHADOW/false-flag and backup integrity rechecks PASS.
- PR12 was already MERGED when inspected; the conditional close-if-open requirement is satisfied without a new action.
- Durable receipt first preserved in `fff1e331f6a8fdb5f77ea3fad6d757bcdc94acda`; current candidate's exact repository QA and CI are recorded in PR14 before readiness.

This completes manual foundation verification only. Oracle/discovery/supervised/controller certification and runtime installation remain open in 0836–0844.
