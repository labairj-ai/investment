# TODO 0869 — Review nine existing Scout candidates and close failed setup handles

- **ID:** 0869
- **Status:** in-progress
- **Created:** 2026-11-06
- **Risk:** L5 original candidate classification retained; bounded connection lifetime correction only
- **Base:** 60a2eedc5bcae6e342311e72e07c6cec2d7c796e
- **Source:** Owner task to evaluate all nine production proposals, implement worthwhile low-risk work, test, merge, deploy and record outcomes against their existing IDs.

## Plan and acceptance

Production-ledger review and ranking: docs/reviews/scout-nine-20261106.md. Canonical implementation candidate: 760aae43-7c6b-43af-9ee2-0c7ff427952e. No new candidate or infrastructure. One reproduced resource-lifetime defect in agent_db._connect: setup errors leave its connection open.

- [x] Review all nine actual proposal/evidence/event records; identify obsolete CI signal, repeated proposals and overlapping deferred-import graph signals.
- [x] Demonstrate both setup-PRAGMA resource leaks before correction; close only on setup failure and preserve error identity, SQL, WAL and foreign keys afterward.
- [x] Focused regressions and cold-import checks; retain earlier PR44/45 cleanup behavior and all financial/trading safeguards.
- [ ] Exact-head CI, unchanged TODO/release-baseline/CC gates and complete diff review.
- [ ] Existing owner merge/release with merged-main CI and protected-state observation; append genuine outcomes against all nine original IDs. No autonomous acceptance credit or new candidates.
