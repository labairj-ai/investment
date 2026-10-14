# Require GitHub Event Authority for All CI Contract Validation

- **ID:** 0731
- **Status:** in-progress
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0724, 0728

## Problem

The CI CLI currently permits caller-provided prior-ref/file when the event payload is absent. GitHub event authority must always be mandatory in CI.

## Implementation guardrails and acceptance

- [ ] When GITHUB_ACTIONS=true or CI=true require readable valid GITHUB_EVENT_PATH, supported GITHUB_EVENT_NAME and exact event authority (PR base SHA or push before).
- [ ] Reject missing/unreadable/malformed payloads, unsupported events, missing/malformed SHA, all-zero push before and all caller prior-file substitutions.
- [ ] Prefer rejecting all explicit prior-ref inputs in CI, even if equal; CI computes authority exclusively.
- [ ] Offline prior-ref/file inputs remain available only outside CI.
- [ ] Retain protected --update-baseline prohibition; fixture setup must not remove CI flags globally or bypass event authority.
- [ ] Align diagnostics with component-specific forward bump rules; never recommend simulator_version as a substitute for simulator_contract_version or model_version.
- [ ] Add table-driven subprocess authority tests for both CI flags and PR/push shapes; full tests and release gates must be green without waivers.
- [ ] The supplied description ends at “Align user-f”; remaining diagnostic scope follows the stated problem.

## Completion

Implementation complete. Full local QA complete; real GitHub Actions verification pending.

Full suite: 2,440 passed / 16 skipped / 0 failed; exact release inventory and TODO status gates passed.

Focused fingerprint suite: 284 passed under GITHUB_ACTIONS=true. Protected inventory: model 85 functions / 4 types / 28 constants / 16 config keys; simulator 78 functions / 4 types / 16 constants / 28 config keys.

Exact trusted-prior migration check passed against fc1d475ef43998cf80c4d24b8ef6f093268f7037. Recommendation source, runtime versions, production data and release waivers are unchanged.
