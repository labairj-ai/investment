# Lot-add accepts negative inventory

- **ID:** 0756
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** none
- **Review finding:** 12

## Problem and reproduced behavior

Location: [lot validation and insertion](../../serve.py:2620).

Validation checks only that fields are truthy. Negative shares, negative costs and malformed purchase dates reach storage; finite-number checks are also absent. Reproduction submitted `shares=-20` to a 100-share holding: the handler returned success, stored a negative lot, and reduced CSV inventory to 80 without recording a sale. Negative lots subsequently break FIFO assumptions.

## Touches

- `serve.py`
- `portfolio_positions.py`

## Acceptance criteria

- [x] Reject nonfinite, nonnumeric, zero/negative share quantities before opening a write transaction.
- [x] Define a valid cost-basis policy, including whether legitimate zero-basis acquisitions are supported; reject negative and nonfinite costs.
- [x] Parse ISO purchase dates and enforce supported temporal rules; normalize ticker input before persistence.
- [x] The reproduced -20-share lot request must return a client error and leave the database, CSV and snapshots unchanged.
- [x] Test malformed dates, future dates, NaN/Infinity, whitespace/aliases and legitimate fractional-share lots across relevant add/edit boundaries.

## Evidence and validation

- [Review finding 12](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Finite positive shares, nonnegative finite costs and parsed nonfuture dates are validated before writes; fractional/zero-basis acquisitions supported.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
