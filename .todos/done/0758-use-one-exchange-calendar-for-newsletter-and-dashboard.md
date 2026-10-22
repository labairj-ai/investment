# Newsletter and dashboard use a federal holiday calendar as an exchange calendar

- **ID:** 0758
- **Status:** done
- **Created:** 2026-10-21
- **Priority:** normal
- **Depends:** none
- **Review finding:** 14

## Problem and reproduced behavior

Locations: [newsletter calendar](../../send_newsletter_main.py:110), [dashboard calendar](../../generate_dashboard.py:39).

Both treat every US federal holiday as an exchange closure, disagreeing with the project's NYSE calendar. Reproduction: October 12, 2026 is classified closed by the newsletter and open by `trade_engine.market_calendar`. The newsletter writes zero daily changes, and dashboard chart filtering drops that session. The same mismatch occurs for Veterans Day.

## Touches

- `send_newsletter_main.py`
- `generate_dashboard.py`
- `trade_engine/market_calendar.py`

## Acceptance criteria

- [x] Replace federal-holiday-as-market-holiday logic with one canonical exchange-session calendar.
- [x] October 12 and November 11, 2026 must remain trading sessions in newsletter storage and dashboard chart filtering, consistent with execution.
- [x] Good Friday, observed exchange holidays, weekends and early-close sessions must retain correct behavior.
- [x] A mocked newsletter run on an exchange-open federal holiday must preserve daily changes and chart dates.
- [x] Audit other calendar copies and remove contradictory scheduling/filtering implementations without introducing a second source of truth.

## Evidence and validation

- [Review finding 14](../../docs/plans/investment-deep-review-20261021.md).
- [Offline reproductions](../../docs/evidence/investment-deep-review-20261021/reproduce.py) and [captured results](../../docs/evidence/investment-deep-review-20261021/results.json).
- Convert this finding into focused regression tests at the affected boundary; preserve all unrelated tests and release safeguards.
- For protected covered-call behavior changes, classify the change and satisfy existing version/manifest/behavioral-contract gates. Do not waive failing tests or change production evidence to make validation pass.

## Completion evidence

Implemented locally on October 21, 2026. Newsletter and dashboard use the canonical exchange calendar; federal-open holiday and Good Friday regressions pass.

- Full suite: 2,633 passed / 16 skipped / zero failures.
- Final focused post-suite checks: 172 passed; final inventory/learning regressions include all new review cases.
- Release failure inventory, trusted-prior CC behavioral contract and TODO status checks pass; no waivers added.
- [Implementation and recovery notes](../../docs/plans/investment-backlog-implementation-20261021.md).
- [Machine-readable validation](../../docs/evidence/investment-backlog-implementation-20261021/validation.json).

Completion covers local code and regression validation. Deployment and historical production-data reconciliation were not performed; the supplied read-only audit and documented backup/reconciliation procedure cover follow-up operations.
