# Equity sales can remove shares backing an open covered call

- **ID:** 0749
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** 0748
- **Review finding:** 05

## Problem and reproduced behavior

Location: [equity coverage rule](../../trade_engine/risk_engine.py:504).

The equity sell check subtracts pending equity sells but does not reserve shares for existing short calls. Reproduction with 100 shares and a filled short call **APPROVED** selling all 100 shares, leaving zero coverage. The Advisor has a separate CC conflict check, but direct execution uses this risk core and needs the same protection.

## Touches

- `trade_engine/risk_engine.py`
- `agents/advisor/trade_impact.py`
- `trade_engine/execution_engine.py`

## Acceptance criteria

- [x] Reserve underlying shares backing filled and pending short calls before approving equity sales.
- [x] With 100 shares and one open call, selling 100 shares must reject; with 150 shares, selling 50 can pass and selling 51 must reject.
- [x] Include partially filled equity sells and concurrent working option orders in post-sale coverage.
- [x] Explicitly define how option close/expiration/assignment evidence releases coverage; do not infer release from an absent local row.
- [x] Keep execution evaluation and Advisor coverage previews consistent, including remaining-quantity checks at PRE_FILL.

## Evidence and validation

- [Review finding 5](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Equity sales preserve shares backing open and reserved calls; partial excess holdings remain sellable.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
