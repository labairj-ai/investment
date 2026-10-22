# FIFO sales do not update the surviving position's average cost

- **ID:** 0755
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0754
- **Review finding:** 11

## Problem and reproduced behavior

Location: [CSV sale update](../../serve.py:2838).

Only `Shares` changes. After FIFO removes a cheaper lot, `AvgCost` still includes that sold lot. Reproduction sold the 50 shares costing $100 from a 100-share position whose other 50 shares cost $200: remaining `AvgCost` stayed **$150 instead of $200**. CSV-based gain and covered-call cost-floor calculations use the wrong basis. Multiple matching CSV rows also each receive the full remaining ticker quantity.

## Touches

- `serve.py`
- `portfolio_positions.py`
- `covered_call_rec.py`

## Acceptance criteria

- [x] After a FIFO sale, recompute the remaining weighted average cost from surviving positive-share lots.
- [x] For 50 shares at $100 plus 50 at $200, selling the cheaper 50 must leave 50 shares at $200 average cost, not $150.
- [x] Persist exactly one canonical CSV position per normalized ticker; multiple old rows must not each receive total remaining quantity.
- [x] Cover partial sales within a lot, multiple consumed lots, zero-share exits, aliases and undo/restoration.
- [x] Verify CSV-based gain calculations and covered-call cost floors consume the corrected surviving basis.

## Evidence and validation

- [Review finding 11](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Surviving FIFO basis is recomputed from lots, with one normalized CSV position per ticker.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
