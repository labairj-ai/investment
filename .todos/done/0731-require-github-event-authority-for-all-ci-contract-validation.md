# Require GitHub Event Authority for All CI Contract Validation

- **ID:** 0731
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** high
- **Depends:** 0724, 0728

## Problem

The CI CLI currently permits caller-provided prior-ref/file when the event payload is absent. GitHub event authority must always be mandatory in CI.

## Implementation guardrails and acceptance

- [x] When GITHUB_ACTIONS=true or CI=true require readable valid GITHUB_EVENT_PATH, supported GITHUB_EVENT_NAME and exact event authority (PR base SHA or push before).
- [x] Reject missing/unreadable/malformed payloads, unsupported events, missing/malformed SHA, all-zero push before and all caller prior-file substitutions.
- [x] Prefer rejecting all explicit prior-ref inputs in CI, even if equal; CI computes authority exclusively.
- [x] Offline prior-ref/file inputs remain available only outside CI.
- [x] Retain protected --update-baseline prohibition; fixture setup must not remove CI flags globally or bypass event authority.
- [x] Align diagnostics with component-specific forward bump rules; never recommend simulator_version as a substitute for simulator_contract_version or model_version.
- [x] Add table-driven subprocess authority tests for both CI flags and PR/push shapes; full tests and release gates must be green without waivers.
- The supplied description ends at “Align user-f”; remaining diagnostic scope follows the stated problem.

## Completion

Implementation complete. Local and real GitHub Actions QA complete.

Full suite: 2,440 passed / 16 skipped / 0 failed; exact release inventory and TODO status gates passed.

Focused fingerprint suite: 284 passed under GITHUB_ACTIONS=true. Protected inventory: model 85 functions / 4 types / 28 constants / 16 config keys; simulator 78 functions / 4 types / 16 constants / 28 config keys.

Exact trusted-prior migration check passed against fc1d475ef43998cf80c4d24b8ef6f093268f7037. Recommendation source, runtime versions, production data and release waivers are unchanged.


CI: [passing implementation run](https://github.com/labairj-ai/investment/actions/runs/38491829391) on 9d320bd: **2,438 passed / 18 skipped / 0 failed**. TODO status, exact release inventory and CC contract-check steps all executed and passed. No new waiver.

Prior engine: `7e6a8a4cbc5ee2d5ca5b824e9d94be8addad49c9de52d364a8eb3a3727281b6d`; prior simulator: `9ac625ac79d8ecf860b5994778337ae5f4628e515d09cae2c1444ccd64970e39`.

Proposed engine: `fccf8fce066e0dc582b5838fa001c63a8e73cfcb3237677fe6264668dd0216bb`; proposed simulator: `36094c7261e2f31307ca43635cc29ce23e5b6ea55dd5be85e2ccae586118c13f`. Local macOS/Python 3.9 and CI Linux/Python 3.12 hashes agree.
