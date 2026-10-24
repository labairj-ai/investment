# TODO 0846 — Replace Complex Owner Readiness with READY / NOT READY

- **ID:** 0846
- **Status:** backlog
- **Priority:** high
- **Risk:** L2 — observability/UI
- **Depends:** existing Development Agent dashboard
- **Blocks:** none

## Objective

Hide internal governance and certification complexity from the owner. The dashboard should answer Development Agent: READY or Development Agent: NOT READY — reason.

## Owner-facing categories

- Validation unavailable.
- Discovery unavailable.
- Deployment unavailable.
- GitHub authorization unavailable.
- Safety check failed.
- Evidence still accumulating.
- Emergency stop active.
- Ready.

## Internal diagnostics

Retain detailed evidence, hashes, TTLs, protocol versions, receipts and raw blockers for debugging. Expose them only in diagnostic details/API.

## Required tests

- [ ] Missing validator → NOT READY — validator unavailable.
- [ ] Stale GitHub protection → NOT READY — GitHub safety check unavailable.
- [ ] Kill switch → NOT READY — emergency stop active.
- [ ] All required controls pass → READY.
- [ ] Detailed diagnostics remain available.
- [ ] READY never disagrees with runtime admission.

## Guardrails

Presentation simplification only. Never weaken a runtime gate to make the dashboard green.

## Done when

The owner can understand readiness without knowing internal Development Agent protocols.
