# Detect Missing Experiment Work and Outcomes

- **ID:** 0564
- **Status:** done
- **Created:** 2026-09-21
- **Priority:** high
- **Depends:** 0563

## Problem

A completed Opportunity Hunter sweep can leave no prospective cohort if experiment capture fails silently. Running a labeler or MTM process also does not establish that all work due by the evaluation time was completed.

## Proposed approach

- Define eligible sweep membership independently from actual experiment rows, using authoritative Opportunity Hunter run/universe lineage and the prospective activation boundary. Join by stable sweep IDs, not loose timestamp proximity; distinguish learning-model sweeps from Opportunity Hunter sweeps.
- Require every eligible completed Opportunity Hunter sweep to produce a cohort or a linked explicit exclusion reason. Report expected, observed, excluded and unexplained missing counts. An unexplained gap is a RED continuity failure after the completion grace window; documented exclusions remain visible and rising exclusion rates are YELLOW.
- Reconcile existing cohort and exclusion records without fabricating excluded cohorts or backfilling prospective evidence. Explicitly skipped/no-candidate sweeps need documented eligibility semantics so they cannot hide missing work.
- Check due labels using existing 5/21/63 trading-session horizon and point-in-time outcome rules. Distinguish not due, labeled, overdue, and explicitly unevaluable because source prices/labels failed; unevaluable is not a fabricated outcome or successful label.
- Require expected learning sweep completion and complete virtual-book daily rows for due sessions and applicable books. Separate pre-inception/not-yet-due days from incomplete marks, missing prices and missing jobs; never use cost basis as complete MTM.
- Read only existing experiment/learning state; persist findings in watchdog tables. Preserve all prior cohorts and the frozen protocol/epoch.

## Touches

Operational watchdog checks; agents/opportunity_agent.py (completion instrumentation if needed); agents/learning/ ledgers; tests/.

## Done when

- [x] A completed eligible sweep with neither cohort nor exclusion is detected even when no experiment row was ever written.
- [x] Expected = observed + explicitly excluded + unexplained missing is reconciled by sweep lineage; a healthy result requires unexplained missing = 0.
- [x] Fixtures cover duplicate/retried/skipped sweeps, capture exceptions, pre-activation history, due-session boundaries, missing labels and incomplete MTM.
- [x] No prospective data is backfilled, labels imputed, recommendations changed or experiment hashes altered.
- [x] QA evaluation conducted: functionality verified working, no regressions introduced.

## Completion — 2026-09-21

Implemented and deployed on Optiplex. The independent timer and alert-only service pass live checks; the accepted experiment epoch, collection clock and stage-zero influence remain unchanged. See [operational verification](../docs/operational-watchdog.md#verified-deployment--2026-09-21). Full local regression: 1,376 passed, 16 skipped; implementation CI passed. Transport failure/deduplication tests used fake senders; no synthetic emails were sent.
