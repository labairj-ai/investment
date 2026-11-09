# TODO 0869 — Review nine existing Scout candidates and close failed setup handles

- **ID:** 0869
- **Status:** done
- **Created:** 2026-11-06
- **Risk:** L5 original candidate classification retained; bounded connection lifetime correction only
- **Base:** 60a2eedc5bcae6e342311e72e07c6cec2d7c796e
- **Source:** Owner task to evaluate all nine production proposals, implement worthwhile low-risk work, test, merge, deploy and record outcomes against their existing IDs.

## Plan and acceptance

Production-ledger review and ranking: docs/reviews/scout-nine-20261106.md. Canonical implementation candidate: 760aae43-7c6b-43af-9ee2-0c7ff427952e. No new candidate or infrastructure. One reproduced resource-lifetime defect in agent_db._connect: setup errors leave its connection open.

- [x] Review all nine actual proposal/evidence/event records; identify obsolete CI signal, repeated proposals and overlapping deferred-import graph signals.
- [x] Demonstrate both setup-PRAGMA resource leaks before correction; close only on setup failure and preserve error identity, SQL, WAL and foreign keys afterward.
- [x] Focused regressions and cold-import checks; retain earlier PR44/45 cleanup behavior and all financial/trading safeguards.
- [x] Exact-head CI, unchanged TODO/release-baseline/CC gates and complete diff review.
- [x] Existing owner merge/release with merged-main CI and protected-state observation; append genuine outcomes against all nine original IDs. No autonomous acceptance credit or new candidates.


## Evidence review — 2026-11-09

Closed against PR #53, implementation `6e2b847d94c13ada6512718dc0a27292dc7639fa`, merge/deployment `da252fcd36f7ecb1a6ca0fdaf2394b05950cba94`. Exact-head CI [42313078302](https://github.com/labairj-ai/investment/actions/runs/42313078302) and retained merged-main validation passed all eight gates (4268 passed, 18 existing skips). DEPLOYED_HEALTH_VERIFIED receipt confirms protected state unchanged. recorded-outcomes.json verifies nine original IDs, unchanged previous events and zero new candidates: one bounded fix deployed, five deferred remainders and three rejected proposals. The outcome UI shows one IMPLEMENTED, five DEFERRED and three REJECTED, all L5. Closing this review/fix task does not close the broad deferred candidate scopes or grant autonomous credit.

[Evidence matrix and retained receipt](../../docs/evidence/development-todo-review-20261109/README.md). Historical progress notes above describe their original dates; this review records final disposition. Supervised, autonomy, physical-device and overall certification remain separate.
