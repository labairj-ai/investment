# Complete CC Behavioral Source Fingerprint Coverage

- **ID:** 0729
- **Status:** done
- **Created:** 2026-10-13
- **Priority:** critical
- **Depends:** 0724, 0725, 0726, 0728

## Problem

The existing fingerprints omit recommendation and prospective simulator behavior; release authorization cannot detect unprotected source changes.

## Implementation guardrails and acceptance

- [x] Create explicit inspectable canonical model/simulator function and constant registries, named source components, configuration keys and fingerprint-definition schema.
- [x] Protect drift_model touch_probability path_oracle path_metrics eligibility surface regime_model overwrite execution tax_metrics utility divergence prepare and relevant indirect recommendation/economic helpers and constants.
- [x] Protect fill_model start_from_decision context_for evaluate_snapshot terminal_outcome censor_version_mismatch missed_intervals advance, OPEN_CHAIN_POLICY, management identity, simulator constants and all protected policy/version identities.
- [x] Hash a canonical named structure deterministically across macOS/Linux; no timestamps, paths, addresses, object repr or runtime monkeypatch identity.
- [x] Restrict config hashing to behavioral keys; docs/dashboard/TODO/logging outside protected surface must remain stable. Avoid entire-file hashing and circular imports.
- [x] Do not automatically bump model/simulator versions, change economics, scoring, behavior or production data; V3 remains observe-only.
- [x] Fingerprint-composition migration must be explicit, intentional, manifest-bound and checked against trusted prior Git state; preserve 0724–0728 release rules.
- [x] Inventory/classify every V3 and virtual function and relevant rec helpers, then independently mutate every protected function/constant/config key.
- [x] Run focused fingerprint/change-control/adversarial tests, full pytest tests/ -v --tb=short --junitxml=test-results.xml, release inventory, TODO gate and authorized contract transition.
- [x] Verify real GitHub Actions green without new waivers; record prior/proposed hashes and protected counts.

## Completion

Implementation complete. Local and real GitHub Actions QA complete.

Full suite: 2,440 passed / 16 skipped / 0 failed; exact release inventory and TODO status gates passed.

Focused fingerprint suite: 284 passed under GITHUB_ACTIONS=true. Protected inventory: model 85 functions / 4 types / 28 constants / 16 config keys; simulator 78 functions / 4 types / 16 constants / 28 config keys.

Exact trusted-prior migration check passed against fc1d475ef43998cf80c4d24b8ef6f093268f7037. Recommendation source, runtime versions, production data and release waivers are unchanged.


CI: [passing implementation run](https://github.com/labairj-ai/investment/actions/runs/38491829391) on 9d320bd: **2,438 passed / 18 skipped / 0 failed**. TODO status, exact release inventory and CC contract-check steps all executed and passed. No new waiver.

Prior engine: `7e6a8a4cbc5ee2d5ca5b824e9d94be8addad49c9de52d364a8eb3a3727281b6d`; prior simulator: `9ac625ac79d8ecf860b5994778337ae5f4628e515d09cae2c1444ccd64970e39`.

Proposed engine: `fccf8fce066e0dc582b5838fa001c63a8e73cfcb3237677fe6264668dd0216bb`; proposed simulator: `36094c7261e2f31307ca43635cc29ce23e5b6ea55dd5be85e2ccae586118c13f`. Local macOS/Python 3.9 and CI Linux/Python 3.12 hashes agree.
