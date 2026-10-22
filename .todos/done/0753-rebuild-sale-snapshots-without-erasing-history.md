# Selling leaves stale snapshots or deletes valid history

- **ID:** 0753
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** high
- **Depends:** 0754
- **Review finding:** 09

## Problem and reproduced behavior

Locations: [history purge](../../serve.py:2852), [today update](../../serve.py:2865).

A same-day full sale neither updates nor deletes today's row because the update requires positive remaining shares. Reproduction left a 100-share/$15,000 snapshot after all shares were sold. A backdated partial sale deletes **every subsequent holding row** before attempting today's update, so today's row is then absent and cannot be repaired by that update. Reproduction of a 20-share backdated sale left zero current rows instead of an 80-share position. Portfolio/layer aggregates are not brought into agreement either.

## Touches

- `serve.py`
- `agents/snapshot.py`
- `generate_dashboard.py`

## Acceptance criteria

- [x] A same-day full sale must remove/zero the sold holding as appropriate and recompute all affected portfolio/layer aggregates and weights.
- [x] A backdated 20-share sale against 100 shares must leave an 80-share current snapshot, not remove all subsequent holding rows.
- [x] Define and implement historical share reconstruction using dated transactions; preserve subsequent purchases and unrelated ticker history.
- [x] Partial and full sales must yield agreeing CSV, cost lots, holding_day, layer_day and portfolio_day projections.
- [x] Provide a read-only inconsistency inventory and a repeatable repair plan with backup/provenance requirements before changing historical production data.

## Evidence and validation

- [Review finding 9](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Dated inventory reconstruction preserves quotes/history and updates holding/layer/portfolio projections, including zero-share exits.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
