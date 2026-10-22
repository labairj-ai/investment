# TODO 0809 — Bind Dashboard Human Decisions to a Unique Authenticated Operator Identity

- **ID:** 0809
- **Status:** in-progress
- **Created:** 2026-10-22
- **Priority:** medium
- **Depends:** 0768
- **Blocks:** strong 0801 supervision evidence

## Problem

Dashboard mutations currently authenticate using a shared Development Agent API token and record the actor as `dashboard-operator`.

This proves possession of the token, but does not establish which specific human made the decision.

Prospective supervised pilot evidence should have attributable human identity.

## Scope and acceptance

- [ ] Integrate dashboard authorization with a unique authenticated operator identity.
- [ ] Prefer identity supplied by the trusted reverse proxy/Tailscale/authentication boundary.
- [ ] Do not accept actor identity from request JSON.
- [ ] Bind each decision to:
  - verified user identity
  - authentication source
  - timestamp
  - decision nonce
  - exact candidate context
- [ ] Preserve API token as defense-in-depth if useful, but not as the sole identity source.
- [ ] Reject mutations when unique identity cannot be established for supervised certification workflows.
- [ ] Keep secrets and raw authentication credentials out of the ledger.
- [ ] Display authenticated actor in audit history.
- [ ] Preserve same-origin/Content-Type mutation checks.
- [ ] CLI identity behavior remains unchanged.

## QA requirements

- [ ] Request body claiming another actor cannot alter recorded identity.
- [ ] Shared token without verified operator identity cannot create qualifying supervised evidence.
- [ ] Two different authenticated operators produce distinguishable audit records.
- [ ] Replay nonce remains rejected.
- [ ] Stale context remains rejected.
- [ ] Read-only dashboard access continues to function without mutating the ledger.

## Implementation guardrails

- Do not store authentication tokens.
- Do not trust model/user-supplied actor names.
- Human identity never grants merge/deployment authority by itself.

## Source

User-supplied 2026-10-22 trust-boundary code-review follow-up. Backlog creation does not authorize implementation, promotion, pilot execution or autonomy activation.

## Implementation checkpoint — 2026-10-22

Implementation is on `codex/trust-boundary-0803-0809`; see the
[implementation plan](../docs/plans/development-agent-trust-boundaries-0803-0809.md)
and [trust-boundary contract](../docs/development-agent-trust-boundaries.md).
Source/fixture validation does not close environmental acceptance. This TODO remains
open pending its complete QA, required human decisions and exact-head CI evidence.
