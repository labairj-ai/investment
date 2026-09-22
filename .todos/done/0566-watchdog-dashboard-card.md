# Display Operational Watchdog Health

- **ID:** 0566
- **Status:** done
- **Created:** 2026-09-21
- **Priority:** normal
- **Depends:** 0563, 0564

## Problem

Operators need a compact view of successful pipeline completion and unresolved operational incidents, separate from statistical evidence about macro effectiveness. A stale watchdog snapshot must not continue to display HEALTHY.

## Proposed approach

- Add a compact System Watchdog card backed by the existing watchdog projection: overall severity, last checked time and per-component status, last success/deadline and concise reason.
- Include serve/DB, current acceptance identity, production influence, holding/candidate coverage work, Opportunity Hunter, expected/observed/excluded/unexplained cohorts, labeling, learning sweeps, complete MTM and backups.
- Show not-yet-due work and insufficient mature outcomes neutrally. Distinguish operational health from experiment evidence; zero divergence is not an incident.
- Mark expired/missing check results UNKNOWN or STALE rather than healthy. Show incomplete marks and due-label failures explicitly. Link incident evidence to existing records where possible.
- Read-only interface; no restart, re-score, certify, repair, promotion or protocol-edit controls. Document external CLI/journal diagnosis when the dashboard itself is unavailable.

## Touches

generate_dashboard.py; serve.py read-only API; watchdog state projection; tests/; README.md.

## Done when

- [x] Healthy, RED, YELLOW, not-due, unknown and stale states render with text as well as color.
- [x] Displayed counts and timestamps match authoritative watchdog records and expose unexplained missing cohorts.
- [x] Expired heartbeat data cannot show overall HEALTHY; unavailable MTM is not shown as valid performance.
- [x] UI/API checks verify a compact read-only card without altering investment logic or the frozen experiment.
- [x] QA evaluation conducted: functionality verified working, no regressions introduced.

## Completion — 2026-09-21

Implemented and deployed on Optiplex. The independent timer and alert-only service pass live checks; the accepted experiment epoch, collection clock and stage-zero influence remain unchanged. See [operational verification](../docs/operational-watchdog.md#verified-deployment--2026-09-21). Full local regression: 1,376 passed, 16 skipped; implementation CI passed. Transport failure/deduplication tests used fake senders; no synthetic emails were sent.
