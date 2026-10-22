# Historical MTM repair includes future trades and current cash

- **ID:** 0759
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** none
- **Review finding:** 15

## Problem and reproduced behavior

Locations: [holdings reconstruction](../../agents/learning/book_mtm.py:59), [historical run](../../agents/learning/book_mtm.py:178), [cash loading](../../agents/learning/book_mtm.py:201).

`run_mark_to_market(date_str)` prices a historical date but reconstructs holdings from **all fills** and uses today's cash. Reproduction repaired September 21 with a purchase recorded October 20: the future position was included and the row was marked complete, yielding **$1,400 instead of $1,000**. Repairs after later trading silently rewrite historical returns with future information. Synthetic expiration exits also use wall-clock fill timestamps rather than the requested valuation date.

## Touches

- `agents/learning/book_mtm.py`
- `agents/learning/book_simulator.py`
- `operational_watchdog.py`

## Acceptance criteria

- [x] Compute historical holdings and cash from starting capital plus dated fills/fees through the requested valuation session only.
- [x] Repairing September 21 with a purchase dated October 20 must exclude that purchase and produce the correct $1,000 NAV rather than $1,400.
- [x] Synthetic expiration exits must use session-consistent effective timestamps and cannot change current book cash during a historical repair unintentionally.
- [x] Repeated repairs must be idempotent; test future buys/sells, later reopenings, missing prices, complete/incomplete rows and daily-return recalculation.
- [x] Keep actual versus virtual provenance and promotion eligibility explicit; inventory affected historical rows before any production repair.

## Evidence and validation

- [Review finding 15](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. As-of Eastern-session holdings and fee-inclusive cash exclude future fills; historical repairs preserve current cash and following returns.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
