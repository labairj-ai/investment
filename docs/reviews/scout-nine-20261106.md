# Review of the nine existing Scout candidates — November 6, 2026

Source: the actual OptiPlex development-control.sqlite3 candidate records and their append-only events. Reviewed base: 60a2eedc5bcae6e342311e72e07c6cec2d7c796e. No candidate is created by this review. All nine recorded SCORE risk objects classify their original scope L5; resource-only implementation scope does not lower or replace that classification.

Rank prioritizes demonstrated reliability failures, then investment-decision quality, measured performance, and simplicity. These proposals supply no measured performance improvement or decision-quality uplift. Do not infer either benefit from line counts or graph size.

| Rank | Candidate ID | Actual proposal/evidence | Benefit, effort and decision |
|---|---|---|---|
| 1 | 760aae43-7c6b-43af-9ee2-0c7ff427952e | agent_db.py exception boundaries; 4897 lines/28 repeated handlers. Existing PR44 deployed three reader cleanup fixes. | A further setup-PRAGMA failure demonstrably retains an open connection. Small cleanup patch; reliability/resource-lifetime benefit, no SQL/policy change. Implement this bounded fix; defer blanket exception rewrites. |
| 2 | 3963322d-2ca7-4525-8069-6238e635d38d | calibration.py exception boundaries. PR45 ledger outcome records both failed-query connection fixes deployed. | Existing bounded fix remains present and its regressions pass. No additional defect follows from 31 repeated exception types. Further semantic/error-policy refactoring is medium effort and L4/L5 financial-adjacent. Defer the remainder. |
| 3 (tied) | 3f7dd9c0-11c0-419c-8b36-bb347eabf360 | Import-cycle set includes challenger, macro coverage, opportunity and portfolio modules. | Overlapping static graph, including function-local imports; no cold-import failure reproduced. Unproven reliability/decision benefit, medium–large effort, high registration/scoring risk. Defer. |
| 3 (tied) | 777d30bb-1711-4715-a784-82238f4d39ce | Similar November 6 cycle set additionally includes calibration. | Same overlapping graph family, not a distinct runtime failure. Defer together; no separate implementation. |
| 3 (tied) | 509581e8-de67-4627-a207-0a6daf9dda34 | Earlier cycle set includes book_simulator. Existing review already deferred broad refactoring. | Same shared core plus a different learning branch. Unproven benefit, medium–large effort and financial/virtual-fill risk. Defer. |
| 3 (tied) | 6d39521a-1332-4c9d-8187-b682de369cfa | Earlier cycle set includes book_mtm and macro_experiment. Existing review deferred overlap. | Same shared core plus mark-to-market/experiment branches. Unproven benefit and broad financial reach. Defer. |
| 7 | 1a6b5e01-227b-4793-ab52-c127651c79b5 | Historical failed workflow 40867905524; existing review says earnings-date test resolved. | Current exact-main CI passes the cited test and full suite. Zero remaining implementation benefit. Reject as obsolete/already resolved; do not edit the workflow. |
| 8 (tied) | c77d2aa2-6192-46b7-9482-7bb659db478a | November 6 agent_db.py proposal differs from the earlier one by line-count drift (4903 vs 4897), not a concrete new failure. | Reject duplicate of 760aae43-7c6b-43af-9ee2-0c7ff427952e. Attribute the bounded fix to that existing canonical candidate. |
| 8 (tied) | fefcebe9-5d15-47d7-a4df-9924db56a048 | November 6 calibration.py repeated-exception proposal. | Reject duplicate of 3963322d-2ca7-4525-8069-6238e635d38d. Preserve PR45 outcome; no redundant patch. |

## Verification and scope

Before correction, both real in-memory SQLite setup-error cases retain a usable connection; 2 regressions fail and the successful-setup safeguard check passes. After correction, the focused connection, reader and agent database group passes 52 tests. Both original cleanup test suites remain unchanged.

Four isolated cold-import sequences cover agent_db, agents, portfolio_ai, advisor context, calibration/challenger, book simulator/MTM and macro experiment/coverage. All pass with SQLite connection creation and network connects blocked. The detector walks all AST imports, including deferred imports, and prints a sorted cycle member set as arrows; those arrows alone do not demonstrate an eager initialization failure. Do not weaken the safety dependency graph to hide these signals.

The only application change closes a newly allocated connection when setup fails, then re-raises the same exception. Connection timeout, row factory, WAL and foreign-key PRAGMAs are unchanged. No financial SQL, recommendation, scoring, model promotion, position sizing, trading or account behavior is changed. Required exact-head CI, owner merge, merged-main CI and existing source-only release remain required before any deployment claim. Final outcomes are appended against the original candidate IDs after real verification, without autonomous execution/acceptance credit.
