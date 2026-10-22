# Investment bug-fix backlog

Created October 21, 2026 from the [deep review](../docs/plans/investment-deep-review-20261021.md). All 15 items are **implemented locally and archived as done**. See the [implementation receipt](../docs/plans/investment-backlog-implementation-20261021.md). Evidence covers 17 reproduced scenarios. The inaccessible shared-conversation link supplied no additional readable requirements.

| ID | Priority | Finding | Dependencies |
|---|---|---|---|
| [0745](done/0745-canonical-approved-thesis-status.md) | critical | Approved theses are ignored by policy and invalidation readers | none |
| [0746](done/0746-serialize-fifo-sales-before-inventory-read.md) | critical | Concurrent sells can oversell inventory and corrupt the ledger | none |
| [0747](done/0747-restore-only-undone-sale-allocations.md) | critical | Undoing an earlier sale restores shares that are still sold | 0746 |
| [0748](done/0748-reserve-aggregate-covered-call-obligations.md) | critical | Covered-call checks ignore outstanding calls and order reservations | none |
| [0749](done/0749-preserve-call-coverage-on-equity-sales.md) | critical | Equity sales can remove shares backing an open covered call | 0748 |
| [0750](done/0750-retry-intents-after-transient-quote-failures.md) | high | A temporary quote failure permanently strands an approved intent | none |
| [0751](done/0751-require-session-correct-outcome-prices.md) | high | Stale holding prices silently become horizon outcomes | none |
| [0752](done/0752-aggregate-newsletter-holdings-before-ledger-overrides.md) | high | Multi-lot CSV holdings are double-counted in newsletter valuation | none |
| [0753](done/0753-rebuild-sale-snapshots-without-erasing-history.md) | high | Selling leaves stale snapshots or deletes valid history | 0754 |
| [0754](done/0754-synchronize-portfolio-projections-after-undo-and-lot-delete.md) | high | Undo and lot deletion leave authoritative holdings projections inconsistent | 0746, 0747 |
| [0755](done/0755-recompute-surviving-fifo-cost-basis.md) | high | FIFO sales do not update the surviving position's average cost | 0754 |
| [0756](done/0756-validate-lot-quantity-cost-and-purchase-date.md) | high | Lot-add accepts negative inventory | none |
| [0757](done/0757-include-working-buys-in-new-position-caps.md) | high | New-position sizing caps omit working buy reservations | none |
| [0758](done/0758-use-one-exchange-calendar-for-newsletter-and-dashboard.md) | normal | Newsletter and dashboard use a federal holiday calendar as an exchange calendar | none |
| [0759](done/0759-reconstruct-historical-virtual-books-as-of-session.md) | high | Historical MTM repair includes future trades and current cash | none |

## Implementation order (completed)

1. Thesis safety and inventory protection: 0745, 0756, 0746, 0747.
2. Portfolio projections: 0754, then 0753 and 0755.
3. Execution safety: 0748, 0749, 0750 and 0757.
4. Valuation and learning integrity: 0752, 0758, 0751 and 0759.

All listed items passed local validation. The dependency column records the implementation prerequisites.

## Completion rules

Keep items here while backlog/in-progress. Add regression and validation receipts before marking done and moving them into `done/`. Run `venv/bin/python scripts/check_todo_status.py`. Any protected covered-call behavior change must satisfy the existing release authorization gates. Production-data diagnosis/repair and deployment must be recorded separately from local code completion.
