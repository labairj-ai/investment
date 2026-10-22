# Stale holding prices silently become horizon outcomes

- **ID:** 0751
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** none
- **Review finding:** 07

## Problem and reproduced behavior

Locations: [learning price lookup](../../agents/learning/outcome_labeler.py:74), [recommendation outcome lookup](../../agents/outcome_evaluator.py:64).

Both lookups accept the newest cached price before the requested date without any age bound. The learning lookup calls its provider fallback only when no historical cache row exists at all. After a position is exited or data collection stops, a months-old price becomes the horizon price. Reproduction requested October 21 with a January 2 cached price of $100 and a stubbed provider price of $200: it returned $100 and never called the provider. These values feed persisted returns, alpha and learning labels.

## Touches

- `agents/learning/outcome_labeler.py`
- `agents/outcome_evaluator.py`
- `agents/learning/calibration.py`

## Acceptance criteria

- [x] Carry the actual price session into outcome lookup and reject cache rows older than the permitted target-session substitute.
- [x] An October horizon request with only a January holding cache row must fetch the correct history or remain unevaluable; it must not silently use January.
- [x] Use explicit consistent split/dividend adjustment conventions for ticker entry, horizon, excursion and benchmark prices.
- [x] Missing/transient provider data must not permanently prevent later valid labeling; define provenance-preserving correction of existing immutable outcomes.
- [x] Test exited positions, suspended collection, weekends/holidays and provider failures; provide read-only counts of potentially stale historical labels before any repair.

## Evidence and validation

- [Review finding 7](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Exact exchange-session prices, consistent unadjusted benchmark cache, outcome/session provenance, retryable placeholders and Eastern recommendation dates.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
