# Covered-call checks ignore outstanding calls and order reservations

- **ID:** 0748
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** critical
- **Depends:** none
- **Review finding:** 04

## Problem and reproduced behavior

Locations: [coverage check](../../trade_engine/risk_engine.py:523), [contract counting](../../trade_engine/risk_engine.py:169).

`NO_NAKED_OPTIONS` compares just the new request against all owned shares. It does not subtract existing short-call coverage, working option orders, or shares committed to equity sells. `_open_contracts()` counts filled calls but excludes working orders, so the separate contract cap misses reservations too. With 100 shares and one working call, the real risk evaluator **APPROVED** another call under the default one-contract cap. Combined coverage requires 200 shares.

## Touches

- `trade_engine/risk_engine.py`
- `trade_engine/execution_engine.py`
- `agents/advisor/risk_preview.py`

## Acceptance criteria

- [x] Calculate aggregate filled short calls plus remaining working/pending option commitments; subtract underlying shares reserved by equity sells.
- [x] With 100 shares and one working call, a second call must fail both applicable coverage/contract-cap checks under the default policy.
- [x] Count partially filled orders by remaining exposure without double counting their fills; account and underlying/contract identity must remain explicit.
- [x] Apply consistent exclusion of an order own reservation in PRE_FILL revalidation; cancellation and closing fills must release commitments exactly once.
- [x] Exercise PRE_ORDER, PRE_FILL and read-only Advisor preview with the same scenarios, including different accounts and expirations.

## Evidence and validation

- [Review finding 4](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Filled/reserved calls, pending submit/cancel states, per-account coverage and contract caps are counted in the shared risk core.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
