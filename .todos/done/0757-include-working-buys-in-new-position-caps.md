# New-position sizing caps omit working buy reservations

- **ID:** 0757
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** none
- **Review finding:** 13

## Problem and reproduced behavior

Location: [new-position rule](../../trade_engine/risk_engine.py:440).

The general position cap includes working buys, but `MAX_NEW_POSITION_WEIGHT` checks only the new intent's notional. While the symbol is not yet filled, multiple working buys each qualify independently. Reproduction approved another $500 buy with a $500 working buy and $10,000 NAV: **10% committed exposure despite the 5% new-position limit**.

## Touches

- `trade_engine/risk_engine.py`
- `agents/advisor/risk_preview.py`

## Acceptance criteria

- [x] Include same-symbol working buy reservations when enforcing the maximum initial/new-position weight.
- [x] With $10,000 NAV, a working $500 buy and a 5% new-position limit, a second $500 buy must reject.
- [x] Define how partially filled initial entries remain subject to the initial allocation budget rather than silently switching to the larger existing-position cap.
- [x] Exclude an order own reservation during PRE_FILL while counting all other commitments; scope every query by account.
- [x] Test partial fills, cancellation/release, multiple accounts and both persisted evaluation and read-only preview.

## Evidence and validation

- [Review finding 13](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. New-position risk caps count reservations and partially filled initial allocations, excluding own order on PRE_FILL.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
