# TODO 0833 — Make Runtime Autonomy Admission Enforce the Same Evidence as Promotion

- **ID:** 0833
- **Status:** in-progress
- **Priority:** critical
- **Risk:** L5 — autonomy authority
- **Depends:** 0831 design, existing stage_control.py, promotion.py
- **Blocks:** PR #13 merge, 0831 completion, any future autonomy activation
- **Scope:** autonomy-readiness admission only

## Problem and design

Promotion NO-GO safety requirements must not be advisory while runtime admission independently permits autonomous starts. Extract a read-only shared evidence primitive consumed by promotion and stage/runtime admission. Do not call promotion.report() directly from runtime: promotion preparation intentionally requires disabled autonomy, while shared safety qualification must work before and after activation.

## Mandatory shared evidence

- [ ] 0825–0830 acceptance complete.
- [ ] Three distinct qualifying supervised successes and seven America/New_York calendar days; preserve the minimum thresholds.
- [ ] Current structural harness and current complete technical certificate PASS.
- [ ] Current independent oracle and Deployment Agent certificates: PASS, fixture_only=false, current harness, within TTL.
- [ ] Fresh effective GitHub protection PASS and fresh authenticated production snapshot PASS.
- [ ] No emergency stop/kill switch, unresolved pause, abnormal deployment or repeated pipeline-failure condition.
- [ ] Every qualifying release has valid fixed-controller deployment evidence.
- [ ] Every qualifying run has explicit post-fix measurement: defect_recurrence_checked=true and defect_recurred=false.
- [ ] Required scheduler/discovery health is current and genuine.
- [ ] auto_merge=false, required_human_merge=true, maximum risk L2 and bounded daily cap.
- [ ] Shared function mutates nothing and grants no authority.

## Owner promotion boundary

- [ ] Define OWNER-AUTONOMY-PROMOTION autonomy-promotion-1, separate from report/config/PR review.
- [ ] Bind repository, structural harness, activation PR, exact activation head, requested stage, L2 risk maximum, daily cap, verified owner identity, timestamp, single-use nonce and rationale.
- [ ] Require both qualifying evidence and an authenticated owner promotion decision; config alone cannot activate.
- [ ] Report never creates an authorization record; agent cannot create it.
- [ ] If full authenticated ingestion is outside this PR, provide the explicit contract/interface and keep activation impossible until a reviewed authenticated issuer/verifier exists.
- [ ] New harness or activation head invalidates prior authorization.

## Required tests and QA

- [ ] Legacy stage criteria pass but recurrence missing: promotion NO-GO and runtime rejection.
- [ ] Missing, fixture, expired or wrong-harness oracle certificate rejects runtime.
- [ ] Missing, fixture, expired or wrong-harness deployment certificate rejects runtime.
- [ ] Stale/insufficient scheduler, protection/snapshot, unresolved incident, pause or repeated failure rejects runtime.
- [ ] Every mandatory shared blocker has report/runtime parity coverage.
- [ ] Complete real-shape evidence passes the shared gate and may recommend owner review, without enabling autonomy/merge/deploy.
- [ ] Config true without authenticated owner promotion remains denied.
- [ ] Changed harness/head makes activation binding invalid.
- [ ] Existing stage/promotion tests remain green; dashboard uses the same blocker semantics.
- [ ] No disabled-autonomy circularity or ledger mutation during qualification.

## Guardrails

Do not lower thresholds, let config activate autonomy, create owner authority from agent output, enable any authority, use investment P&L, or admit L3+ autonomous work.

## Done when

- [ ] Promotion/runtime share safety criteria; no NO-GO safety reason coexists with an allowed autonomous start.
- [ ] Explicit owner promotion remains required and fail-closed.
- [ ] Focused/full tests and exact-head CI pass.
