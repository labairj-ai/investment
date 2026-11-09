# TODO 0868 — Show latest Scout discoveries separately from priority

- **ID:** 0868
- **Status:** done
- **Created:** 2026-11-06
- **Risk:** L3 read-only development-ledger projection and existing candidate cards
- **Base:** b67ef328e58ccdf9f2972ccf00b76ed94e17802e
- **Source:** Owner task to investigate missing November 6 discoveries and implement, validate, merge and deploy the Overview correction.

## Plan and acceptance

All four November 6 candidates exist in the authoritative development ledger and appear first in the newest-first API. Overview's five risk-sorted records hide them because UNKNOWN risks tie and creation time sorts oldest first. Keep priority ordering; project the latest natural run and latest successful run's newly created candidates separately. Reuse candidate rendering, scheduler success checks and read-only acceptance calculation. No financial, ledger or acceptance writes.

- [x] Confirm four ledger records, live API database path and newest-first candidate results.
- [x] Latest Scout Run reports time, status, discovered count and source-bound acceptance; New Discoveries uses existing inspect cards with score/risk; Priority queue remains separate.
- [x] Focused regressions cover older priority entries, deduplication, failure after success, fixture exclusion and read-only behavior.
- [x] Full relevant validation, unchanged TODO/release-baseline/CC gates, exact-head CI and complete diff review.
- [x] Existing authorized merge/deployment path and live UI/API verification; preserve financial state and original acceptance evidence.

## Deployment constraint

Existing Scout qualification is exact-source-bound. Source deployment must use the existing source-refresh path, which preserves old receipts and carries zero acceptance runs to a different SHA. Never rewrite November 6 evidence or claim its 1/3 for a new source. Keep this TODO open until real release evidence is recorded.


## Evidence review — 2026-11-09

Closed against PR #52, implementation `64a795772e5b7d8cc2c6b39ee426da04388f004f`, merge/deployment `60a2eedc5bcae6e342311e72e07c6cec2d7c796e`. Exact-head CI [42306660504](https://github.com/labairj-ai/investment/actions/runs/42306660504) and merged-main CI [42308366604](https://github.com/labairj-ai/investment/actions/runs/42308366604) passed all eight gates (4265 passed, 18 existing skips). Existing deployment receipt is DEPLOYED_HEALTH_VERIFIED, protected state unchanged. Live API verified the four November 6 discoveries, detail endpoints, separate priority queue and deployed page/assets; seven-width rendering checks passed. No live graphical inspection is claimed for PR52. Original acceptance receipts were preserved with zero credit carried across source changes.

[Evidence matrix and retained receipt](../../docs/evidence/development-todo-review-20261109/README.md). Historical progress notes above describe their original dates; this review records final disposition. Supervised, autonomy, physical-device and overall certification remain separate.
