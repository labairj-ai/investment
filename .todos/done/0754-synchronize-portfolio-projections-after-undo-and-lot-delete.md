# Undo and lot deletion leave authoritative holdings projections inconsistent

- **ID:** 0754
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0746, 0747
- **Review finding:** 10

## Problem and reproduced behavior

Locations: [undo](../../serve.py:2890), [lot deletion](../../serve.py:2726).

These operations mutate only SQLite lots/sales. They do not synchronize `holdings.csv`, daily snapshots or aggregates. Reproduction of a full sale followed by undo restored 100 lot shares but left the CSV empty; the CSV-driven snapshot/newsletter paths omit the restored position. Deleting the only lot left a 100-share CSV holding, so downstream code continues valuing a deleted position.

## Touches

- `serve.py`
- `portfolio_positions.py`
- `agents/snapshot.py`

## Acceptance criteria

- [x] Centralize inventory mutation projections so undo and lot deletion update holdings.csv plus affected holding, layer and portfolio snapshots.
- [x] Full sale then undo must restore the position to both the lot ledger and CSV-driven downstream snapshots.
- [x] Deleting the last lot must not leave a phantom CSV holding; partial deletion must recompute remaining shares and weighted basis.
- [x] Serialize file projections across HTTP threads/processes, use atomic file replacement, and define recovery for DB commit versus projection failure.
- [x] Preserve canonical ticker/layer/date semantics and idempotent retries; cover buy, add-lot, sell, undo and delete consistency.

## Evidence and validation

- [Review finding 10](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. New holding, lot add/delete, sell and undo share durable, serialized, idempotent CSV/snapshot projections with recoverable failure receipts.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
