# Deliver Deduplicated Watchdog Alerts

- **ID:** 0565
- **Status:** done
- **Created:** 2026-09-21
- **Priority:** high
- **Depends:** 0563, 0564

## Problem

Persistent watchdog findings need actionable notification outside the web service. Repeated checks must not create alert storms, and notification failure must not be mistaken for successful delivery.

## Proposed approach

- Reuse existing email transport and configured operator recipients: immediate RED notification on incident opening/escalation and one daily digest of unresolved YELLOW findings. INFO events, no divergence and immature outcomes send no alerts.
- Include component, reason, expected deadline, last success, source record IDs, first/last detection and investigation context. Keep sensitive portfolio data and credentials out of messages.
- Track incident fingerprints, delivery attempts, successful send timestamps and resolution transitions. Bound retries/backoff for notification delivery only; define reminder/recovery policy explicitly and avoid repeated 15-minute notifications.
- Support DB-down alerts through independent fallback state and expose failed delivery/watchdog execution through systemd/journal. Document that an on-host watchdog cannot report complete host/network failure without an external monitor; do not expand v1 into another monitoring platform.
- Provide dry-run/rendered-message fixtures. Actual test sends require explicit user authorization; creating this backlog does not authorize sending email. Never retry or remediate investment jobs.

## Touches

Watchdog runner; existing email transport; watchdog event/delivery state; systemd/; tests/; operator documentation.

## Done when

- [x] RED opens/escalations notify promptly; unresolved YELLOWs appear once in the daily digest; INFO never alerts.
- [x] Repeated checks, failed transport, process restart and incident resolution preserve deduplication and accurate delivery state.
- [x] DB-unavailable incidents can alert without the application database or serve.py; transport failure remains visible.
- [x] Messages and retry policy are tested with fake transport, with no live messages sent by tests.
- [x] QA evaluation conducted: functionality verified working, no regressions introduced.

## Completion — 2026-09-21

Implemented and deployed on Optiplex. The independent timer and alert-only service pass live checks; the accepted experiment epoch, collection clock and stage-zero influence remain unchanged. See [operational verification](../docs/operational-watchdog.md#verified-deployment--2026-09-21). Full local regression: 1,376 passed, 16 skipped; implementation CI passed. Transport failure/deduplication tests used fake senders; no synthetic emails were sent.
