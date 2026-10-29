# TODO 0860 — Build Trusted Validation and Gate Evidence Workspace

- **ID:** 0860
- **Status:** in-progress
- **Created:** 2026-10-29
- **Priority:** critical
- **Risk:** L5 (provisional governance-adjacent; verify with deterministic classifier)
- **Depends:** 0856; existing trusted validator and independent artifact oracle
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Expose real gate evidence and independent verifier outcomes so a user can distinguish strong release proof from CI-only diagnostics, incomplete inventories and candidate-produced claims.

## Target files / interfaces

- `dev_agent/validation.py (read-only manifests/projections)`
- `dev_agent/evidence.py (read-only verification)`
- `dev_agent/dashboard.py (validation display)`
- `tests/test_engineering_control_center.py`
- `scripts/check_development_agent_browser.mjs`

## Scope and acceptance

- [ ] Show gate names and versioned manifest: focused tests, full suite, release baseline, covered-call contract, agent contract, TODO consistency and development governance; include any current canonical trusted gates without silently omitting them.
- [ ] Per gate display status PASS/FAIL/PARTIAL/NOT_RUN/UNAVAILABLE/STALE, command manifest ID, independent verifier identity, exact base/head/source hashes, trusted test-tree identity, image digest, execution timestamps and exit code.
- [ ] Show verified JUnit totals, pass/fail/skip inventory and failure reasons only when externally verified; code `exit=0` alone or candidate-generated JSON/JUnit must never establish PASS.
- [ ] Read independent artifact-oracle receipts via existing trusted mechanisms without opening verifier signing keys or exposing host-only paths to browser, model or candidate code.
- [ ] Aggregate gating is PASS only if *all* required authoritative receipts match current source/head and are fresh; present exact reason for every blocked gate and mismatched SHA.
- [ ] Provide sanitized filterable inspection, trusted receipt link, CI comparison and next-action hints; optional rerun must invoke an existing fixed authorized job, never accept free-form command text or skip requirements.
- [ ] Validation read-only API must page/sanitize evidence with bounded payloads and no raw model prompts, secrets or financial rows.

## QA and negative acceptance

- [ ] Inject forged PASS JSON, candidate-created JUnit, changed source after test, wrong image digest, missing gate, duplicate suite/test IDs, failed test, invented skip counts and malicious links; each must fail or remain UNAVAILABLE.
- [ ] Test stale source hash/approval SHA, expired signed receipt, oracle outage and bad signature; verify aggregate cannot be GREEN.
- [ ] Prove no GET/rerender writes to evidence ledger or production state; browser XSS, oversized data and long error messages.
- [ ] Run independent verified fixture tests and full exact-head gates; cannot claim real oracle certification unless host evidence exists.

## Task-specific guardrails

- Do not modify test thresholds, oracle signing, validator containment, financial baseline commands or gate versions for UI convenience.
- Sanitized metadata only; no general shell executor.
- Never infer actual live test counts from PR descriptions.

## Common implementation guardrails

- Investment remains exclusively on its existing Development Agent; no integration with the standalone Qwen Engineering Agent service.
- No trading, broker, holdings, financial database, scheduler/systemd, autonomy, risk-threshold or production release changes.
- Keep the existing one owner Go/No-Go decision; no separate model-issued approval, merge, deployment or second owner ceremony.
- Independent exact-SHA validation/receipt authority remains outside candidate-written data; any unavailable, stale or untrusted proof fails closed.
- Re-evaluate final diff against deterministic L0–L5 policy; this backlog is conservatively L5 governance-adjacent.
- Record exact commit SHA, focused/full suite, all eight required release gates, adversarial/browser tests and outstanding external acceptance before closure. Fixture PASS does not prove live readiness.

## Done when

All authoritative validation details and blockers are inspectable with independently verifiable source-bound receipts, including negative/adversarial cases.

Source implementation and prepared acceptance matrix: `docs/engineering-control-center.md`. Browser fixtures do not close physical-device, live connector, independent review or rollout acceptance. No deployment is authorized.
