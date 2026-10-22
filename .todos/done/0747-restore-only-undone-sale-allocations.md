# Undoing an earlier sale restores shares that are still sold

- **ID:** 0747
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0746
- **Review finding:** 03

## Problem and reproduced behavior

Location: [undo recreation](../../serve.py:2918).

If a later sale has exhausted a lot, undoing an earlier partial sale recreates the lot with the earlier allocation's `original_shares`, not the shares being undone. Reproduction: buy 100, sell 40, sell 60, undo the 40-share sale. Inventory becomes **100**, although the other 60-share sale remains recorded and inventory should be **40**.

## Touches

- `serve.py`
- `dashboard_transactions.py`

## Acceptance criteria

- [x] When recreating a consumed lot, restore only shares belonging to the undone allocation, not the original pre-sale inventory.
- [x] Buy 100, sell 40, sell 60, undo the first sale: retain the 60-share sale and restore exactly 40 shares.
- [x] Test undoing latest sales, earlier sales, partially surviving lots, multiple lots and repeated undo requests; quantity must never be duplicated.
- [x] Perform undo validation, sale removal and inventory restoration atomically under the shared mutation lock/transaction.
- [x] Original purchase markers reconstructed from open lots and remaining sale allocations must preserve the original purchase quantity.

## Evidence and validation

- [Review finding 3](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Restores allocation quantity rather than original lot quantity; repeated and out-of-order undo conserve inventory.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
