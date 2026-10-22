# A temporary quote failure permanently strands an approved intent

- **ID:** 0750
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** none
- **Review finding:** 06

## Problem and reproduced behavior

Locations: [status change](../../trade_engine/execution_engine.py:516), [next-cycle selection](../../trade_engine/execution_engine.py:816).

The engine marks the intent `APPROVED` before fetching/validating the quote. A missing or rejected quote returns without an order or status rollback. Later cycles select only `PENDING` intents. Reproduction returned `QUOTE_UNAVAILABLE`, left `status='APPROVED'` and zero orders, and processed zero intents on the next cycle. A temporary provider outage therefore silently drops execution indefinitely.

## Touches

- `trade_engine/execution_engine.py`
- `trade_engine/models.py`
- `trade_engine/runner.py`

## Acceptance criteria

- [x] Keep an intent retryable until quote validation and durable order creation succeed, or record an explicit terminal decision with its reason.
- [x] Reproduce quote=None on the first cycle and a valid fresh quote on the next: exactly one order must be submitted rather than silently skipping the intent.
- [x] Test stale quotes, provider exceptions, crossed/wide quotes, limit rejections and TTL expiry with a documented retry/terminal classification.
- [x] Preserve PENDING_SUBMIT broker idempotency and crash recovery; never retry an indeterminate broker submission as a new order.
- [x] Expose stranded legacy APPROVED-without-order intents in a read-only diagnostic and define a safe, explicit reconciliation path.

## Evidence and validation

- [Review finding 6](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Approval is persisted with durable order creation, transient quote failures remain pending, and legacy orphan approvals can retry safely.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
