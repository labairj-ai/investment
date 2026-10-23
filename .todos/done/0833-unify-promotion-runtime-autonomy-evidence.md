# TODO 0833 — Make Runtime Autonomy Admission Enforce the Same Evidence as Promotion

- **ID:** 0833
- **Status:** done
- **Priority:** critical
- **Risk:** L5 — autonomy authority
- **Depends:** 0831 design, existing stage_control.py, promotion.py
- **Blocks:** PR #13 merge, 0831 completion, any future autonomy activation
- **Scope:** autonomy-readiness admission only

## Problem and design

Promotion NO-GO safety requirements must not be advisory while runtime admission independently permits autonomous starts. Extract a read-only shared evidence primitive consumed by promotion and stage/runtime admission. Do not call promotion.report() directly from runtime: promotion preparation intentionally requires disabled autonomy, while shared safety qualification must work before and after activation.

## Mandatory shared evidence

- [x] 0825–0830 acceptance complete.
- [x] Three distinct qualifying supervised successes and seven America/New_York calendar days; preserve the minimum thresholds.
- [x] Current structural harness and current complete technical certificate PASS.
- [x] Current independent oracle and Deployment Agent certificates: PASS, fixture_only=false, current harness, within TTL.
- [x] Fresh effective GitHub protection PASS and fresh authenticated production snapshot PASS.
- [x] No emergency stop/kill switch, unresolved pause, abnormal deployment or repeated pipeline-failure condition.
- [x] Every qualifying release has valid fixed-controller deployment evidence.
- [x] Every qualifying run has explicit post-fix measurement: defect_recurrence_checked=true and defect_recurred=false.
- [x] Required scheduler/discovery health is current and genuine.
- [x] auto_merge=false, required_human_merge=true, maximum risk L2 and bounded daily cap.
- [x] Shared function mutates nothing and grants no authority.

## Owner promotion boundary

- [x] Define OWNER-AUTONOMY-PROMOTION autonomy-promotion-1, separate from report/config/PR review.
- [x] Bind repository, structural harness, activation PR, exact activation head, requested stage, L2 risk maximum, daily cap, verified owner identity, timestamp, single-use nonce and rationale.
- [x] Require both qualifying evidence and an authenticated owner promotion decision; config alone cannot activate.
- [x] Report never creates an authorization record; agent cannot create it.
- [x] If full authenticated ingestion is outside this PR, provide the explicit contract/interface and keep activation impossible until a reviewed authenticated issuer/verifier exists.
- [x] New harness or activation head invalidates prior authorization.

## Required tests and QA

- [x] Legacy stage criteria pass but recurrence missing: promotion NO-GO and runtime rejection.
- [x] Missing, fixture, expired or wrong-harness oracle certificate rejects runtime.
- [x] Missing, fixture, expired or wrong-harness deployment certificate rejects runtime.
- [x] Stale/insufficient scheduler, protection/snapshot, unresolved incident, pause or repeated failure rejects runtime.
- [x] Every mandatory shared blocker has report/runtime parity coverage.
- [x] Complete real-shape evidence passes the shared gate and may recommend owner review, without enabling autonomy/merge/deploy.
- [x] Config true without authenticated owner promotion remains denied.
- [x] Changed harness/head makes activation binding invalid.
- [x] Existing stage/promotion tests remain green; dashboard uses the same blocker semantics.
- [x] No disabled-autonomy circularity or ledger mutation during qualification.

## Guardrails

Do not lower thresholds, let config activate autonomy, create owner authority from agent output, enable any authority, use investment P&L, or admit L3+ autonomous work.

## Done when

- [x] Promotion/runtime share safety criteria; no NO-GO safety reason coexists with an allowed autonomous start.
- [x] Explicit owner promotion remains required and fail-closed.
- [x] Focused/full tests and exact-head CI pass.

## Implementation and validation evidence

- Implemented on PR #13 from verified starting head `df64c4e5813d1cf2fe675d7358e940d3c2b5e3aa`.
- Validated final application code head: `07875aad350b3b1dad113b74cd029db382bae79b`.
- [Exact-head CI PASS](https://github.com/labairj-ai/investment/actions/runs/40014960716): all eight mandatory gates PASS.
- Focused agent suite: 379 passed. Full suite: 3,078 passed, zero failed, 18 existing skips.
- New scheduler/shared-gate/observer adversarial tests: 84 passed in disposable ledgers. No synthetic evidence was issued as a live certificate or operational success.
- All seven requested policy settings remain unchanged; no financial source, investment state, production data, service or timer was changed.
- Owner promotion is an explicitly unavailable authenticated interface, not a completed issuer; config cannot activate runtime. 0826–0831 remain open for their actual live acceptance.
- PR #13 remains draft, and PR #12 is not merged separately.
