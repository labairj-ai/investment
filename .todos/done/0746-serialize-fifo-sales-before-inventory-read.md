# Concurrent sells can oversell inventory and corrupt the ledger

- **ID:** 0746
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** none
- **Review finding:** 02

## Problem and reproduced behavior

Location: [sell handler](../../serve.py:2784).

Lot reads and FIFO allocation happen before a write transaction acquires the SQLite writer lock. Two HTTP threads can both allocate the same shares, then sequentially persist stale allocations. Reproduction started with 100 shares and submitted two concurrent 70-share sales: both succeeded, sales totaled 140, and remaining inventory was incorrectly 30.

## Touches

- `serve.py`
- `tests/test_agent_db.py`

## Acceptance criteria

- [x] Acquire a SQLite write reservation before reading lots and calculating FIFO allocations, then commit the sale and lot mutations together.
- [x] The deterministic two-thread reproduction against 100 shares must allow at most one 70-share sale; the other must return a clear insufficient-inventory result.
- [x] The successful sale must leave 30 shares, one sale record, and one consistent CSV projection without lost updates or partially written files.
- [x] An injected persistence failure must roll back sale and lot changes; avoid success responses after incomplete projection updates.
- [x] Exercise concurrent same-ticker and different-ticker requests with separate connections and verify aggregate quantities reconcile.

## Evidence and validation

- [Review finding 2](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Serialized BEGIN IMMEDIATE FIFO mutations, cross-process locks, rollback and deterministic oversell regressions.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
