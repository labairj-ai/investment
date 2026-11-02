# TODO 0864 — Complete End-to-End Acceptance and Investment UI Replacement

- **ID:** 0864
- **Status:** in-progress
- **Created:** 2026-10-29
- **Priority:** critical strategic
- **Risk:** L5 (conservative; verify via deterministic whole-diff policy)
- **Depends:** 0856, 0857, 0858, 0859, 0860, 0861, 0862, 0863; existing operator release process
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Make the Engineering Control Center the single private Development Agent interface while preserving backend APIs, authentication and protected state. Complete technical and device acceptance through the existing release workflow.

## Target files / interfaces

- `serve.py and Investment-owned route wiring`
- `generate_dashboard.py and Control Center navigation`
- `dev_agent/control_center.py and dev_agent/control_center_assets/index.html`
- `scripts/check_development_agent_browser.mjs`
- `tests/test_engineering_control_center.py`
- `docs/plans/engineering-control-center-investment-v2.md`
- `docs/development-agent.md (documentation updates only, if needed)`

## Scope and acceptance

- [ ] On the private Tailscale service, redirect `/development-agent` to `/engineering/projects/investment`; preserve `/api/development-agent` and all existing backend operations.
- [ ] Verify the Control Center displays the exact current source SHA, readiness blockers, CI status, certification and owner decisions from existing read APIs; discrepancies remain visible and are never silently reconciled by changing source.
- [ ] Use the existing fixed Investment deployment controller and technical checks. The initiating task authorization covers routine UI implementation, merge and deployment; do not request a separate per-PR Go or add owner deployment/promotion objects.
- [ ] Document migration/rollback plan limited to UI/static route: disable new route or revert reviewed code while preserving append-only evidence and production databases. Never roll back financial data.
- [ ] Full regression suite, TODO consistency, development governance and independent oracle/canary gates must pass on exact head with reviewer PASS. Record skipped tests as unchanged/justified and separate operational from fixture checks.
- [ ] Post-deploy verification: authenticated Control Center UI/API smoke, private legacy-route redirect, preserved backend API, candidate/PR read consistency, protected database fingerprint equality, Advisor/trading canary, performance and error budget, delayed observation if controller requires it.
- [ ] Preserve source-to-UI-to-GitHub owner-decision behavior for actions that require it; fail closed on stale head, unavailable oracle, wrong owner and deployment interruption. Routine UI replacement uses the task authorization already given.
- [ ] Do not mark shipped until genuine iOS and Android acceptance from 0863 is observed and real source freshness/host readiness is displayed correctly.

## QA requirements and negative paths

- [ ] Before rollout, demonstrate all mandatory gates at exact SHA; test rollback/kill new feature route without changing agent execution state.
- [ ] Canary route against missing ledger, stale cert, expired source, GitHub outage and partial oracle: UI renders NOT READY/UNAVAILABLE and blocks inappropriate Go.
- [ ] Replay/conflicting owner decisions, wrong head, unauthorized reader and action, fake signed receipt and cross-service/Investment-to-Qwen requests denied.
- [ ] Run baseline parity/latency tests and compare portfolio/holdings/trading SQL/data checksums before/after; do not read financial data into model context.
- [ ] After task-authorized deploy, independently check fixed service, UI, canary, protected-state invariants and delayed health receipt. Retain failed evidence.

## Task-specific guardrails

- The ordinary route replacement may proceed through implementation, tests, merge and deployment under the initiating task authorization and existing technical gates.
- Retain all backend API behavior, authentication, append-only evidence and financial protections.
- Independent backend remains source of truth; UI cannot authorize via cached state.

## Non-negotiable boundaries

- Investment continues to use its own Development Agent and trusted single-owner Go/No-Go gateway, with no dependency on the separate Qwen microservice.
- No change to live portfolio/broker data, policy thresholds, Scout timers, validators, Oracle authority, credential owners, autonomy settings or deployment service solely for dashboard delivery.
- Distinguish committed config/source tests from live host acceptance and exact-SHA authoritative evidence; unknown/unavailable/stale remains blocked.
- This is governance-adjacent L5 planning until deterministic whole-diff classification establishes required review.
- For every completion, retain exact source/PR SHA, trusted gate receipts, all eight existing release gates, focused/full tests, independent review, browser evidence and remaining physical/external acceptance.

## Done when

The private Development Agent route opens the deployed Control Center; required host, security, API and protected-state checks pass; remaining mobile acceptance is recorded. If any required technical observation is unavailable, status stays open.

Implementation contract and remaining acceptance evidence: `docs/engineering-control-center.md`. Browser fixtures do not close physical-device or operational acceptance. Routine UI replacement is covered by the task authorization; high-risk actions outside scope still require the applicable owner decision.
