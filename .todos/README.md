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

## Development-agent operational acceptance — 0795–0802

Created 2026-10-22. This phase proves the environment and controls; it is not an
additional agent-feature phase. 0795 is **in-progress**; 0796–0802 remain **backlog**.

| ID | Task | Priority | Dependencies |
|---|---|---|---|
| [0795](0795-resolve-covered-call-ci-and-behavioral-contract-failures.md) | Resolve Existing Covered-Call CI and Behavioral-Contract Failures | critical | none |
| [0796](0796-restore-exact-head-green-repository-ci.md) | Restore Exact-Head Green Repository CI | critical | 0795 |
| [0797](0797-configure-non-bypass-github-protection.md) | Configure and Verify Non-Bypass GitHub Protection for Development-Agent Changes | critical | 0790, 0796 |
| [0798](0798-provision-digest-pinned-validation-sandbox.md) | Provision Digest-Pinned Development-Agent Sandbox Runtime | critical | 0796 |
| [0799](0799-certify-authentic-production-backup-snapshot.md) | Produce and Certify an Authentic Production Backup Snapshot | critical | 0786, 0796 |
| [0800](0800-complete-development-agent-technical-certification-v2.md) | Complete Development-Agent Technical Certification v2 | critical | 0796, 0797, 0798, 0799, 0792 |
| [0801](0801-execute-prospective-supervised-development-agent-pilots.md) | Execute Three Prospective Supervised Development-Agent Pilots | high | 0800 |
| [0802](0802-authorize-bounded-low-risk-autonomous-operation.md) | Review and Explicitly Authorize Bounded L0–L2 Autonomous Operation | critical | 0801, 0794 |

Critical path: **0795 CC failures → 0796 green CI → 0797 GitHub protection +
0798 sandbox + 0799 authentic snapshot → 0800 technical certification →
0801 three real supervised pilots over ≥7 America/New_York calendar days →
0802 explicit autonomy decision**.

Do not start 0801 until 0795–0800 are truly PASS. 0801 completes the operational
portion of 0793; 0802 also retains dependency on the disabled controls in 0794.
Existing hardening dependencies 0786, 0790 and 0792 remain required; deployed code
is not a substitute for their independent acceptance evidence. Protection changes
belong to a human administrator; autonomy activation requires a separate reviewed
human decision. Creating these files grants neither authority.
