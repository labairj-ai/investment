# Multi-lot CSV holdings are double-counted in newsletter valuation

- **ID:** 0752
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** none
- **Review finding:** 08

## Problem and reproduced behavior

Location: [share override](../../send_newsletter_main.py:693).

The newsletter replaces **each CSV row** with the ticker's full `cost_lots` quantity, then sums the rows without aggregating the ticker. Reproduction used 40- and 60-share rows and 100 shares in the lot ledger: both rows became 100 shares, producing **$20,000 instead of $10,000** at a $100 quote. Portfolio/layer totals are inflated, while `holding_day`'s `(day,ticker)` replacement retains just one duplicate row, creating inconsistent aggregate and holding snapshots.

## Touches

- `send_newsletter_main.py`
- `portfolio_positions.py`
- `agents/snapshot.py`

## Acceptance criteria

- [x] Aggregate CSV lots into one canonical position per normalized ticker before applying any ledger quantity override.
- [x] With 40- and 60-share CSV rows and 100 lot-ledger shares at a $100 quote, produce $10,000 total rather than $20,000.
- [x] Ensure portfolio_day, layer_day and holding_day totals reconcile and only one holding snapshot is persisted per ticker/day.
- [x] Preserve weighted average cost, ticker aliases and a clear policy for conflicting per-lot layers; do not duplicate overrides across rows.
- [x] Run the full newsletter calculation offline with mocked prices and intercepted email delivery; add a multi-lot regression.

## Evidence and validation

- [Review finding 8](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Newsletter uses canonical aggregated positions before ledger overrides; duplicate-lot valuation regression passes.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
