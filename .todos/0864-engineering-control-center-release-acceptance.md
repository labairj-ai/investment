# TODO 0864 — Complete End-to-End Acceptance and Controlled Investment UI Rollout

- **ID:** 0864
- **Status:** backlog
- **Created:** 2026-10-29
- **Priority:** critical strategic
- **Risk:** L5 (conservative; verify via deterministic whole-diff policy)
- **Depends:** 0856, 0857, 0858, 0859, 0860, 0861, 0862, 0863; existing operator release process
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Integrate the new Control Center into Investment's existing deployment only after exact-head security, API/UX, governed owner workflow and protected-state acceptance, preserving rollback and old UI until proven.

## Target files / interfaces

- `serve.py and Investment-owned route wiring`
- `generate_dashboard.py (navigation link only)`
- `dev_agent/dashboard.py`
- `scripts/check_development_agent_browser.mjs`
- `tests/test_engineering_control_center.py`
- `docs/plans/engineering-control-center-investment-v2.md`
- `docs/development-agent.md (documentation updates only, if needed)`

## Scope and acceptance

- [ ] Feature flag/route gate defaults off. Ship read-only first behind Investment's current authenticated API; retain `/development-agent` unchanged for parallel reconciliation until a separate owner-reviewed retirement.
- [ ] Prepare a matrix comparing legacy and new UI for same current candidate/event, exact SHA, readiness blockers, CI status, certification and owner decision; any discrepancy is reported, never silently reconciled by changing source.
- [ ] Use current fixed Investment deployment controller and one owner Go after exact reviewed PR SHA; do not add new owner deployment/promotion objects.
- [ ] Document migration/rollback plan limited to UI/static route: disable new route or revert reviewed code while preserving append-only evidence and production databases. Never roll back financial data.
- [ ] Full regression suite, TODO consistency, development governance and independent oracle/canary gates must pass on exact head with reviewer PASS. Record skipped tests as unchanged/justified and separate operational from fixture checks.
- [ ] Post-deploy verification: authenticated UI/API smoke, legacy route, candidate/PR read consistency, protected database fingerprint equality, Advisor/trading canary, performance and error budget, delayed observation if controller requires it.
- [ ] Audit source-to-UI-to-GitHub owner Go/No-Go flow using non-production/approved test PR; fail closed on stale head, unavailable oracle, wrong owner and deployment interruption.
- [ ] Do not mark shipped until genuine iOS and Android acceptance from 0863 is observed and real source freshness/host readiness is displayed correctly.

## QA requirements and negative paths

- [ ] Before rollout, demonstrate all mandatory gates at exact SHA; test rollback/kill new feature route without changing agent execution state.
- [ ] Canary route against missing ledger, stale cert, expired source, GitHub outage and partial oracle: UI renders NOT READY/UNAVAILABLE and blocks inappropriate Go.
- [ ] Replay/conflicting owner decisions, wrong head, unauthorized reader and action, fake signed receipt and cross-service/Investment-to-Qwen requests denied.
- [ ] Run baseline parity/latency tests and compare portfolio/holdings/trading SQL/data checksums before/after; do not read financial data into model context.
- [ ] After owner-approved deploy, independently check fixed service, UI, canary, protected-state invariants and delayed health receipt. Retain failed evidence.

## Task-specific guardrails

- This backlog PR itself is documentation-only and must not install, enable, restart, merge, deploy or change production flags.
- Do not retire current dashboard until verified parity and separate explicit owner approval.
- Independent backend remains source of truth; UI cannot authorize via cached state.

## Non-negotiable boundaries

- Investment continues to use its own Development Agent and trusted single-owner Go/No-Go gateway, with no dependency on the separate Qwen microservice.
- No change to live portfolio/broker data, policy thresholds, Scout timers, validators, Oracle authority, credential owners, autonomy settings or deployment service solely for dashboard delivery.
- Distinguish committed config/source tests from live host acceptance and exact-SHA authoritative evidence; unknown/unavailable/stale remains blocked.
- This is governance-adjacent L5 planning until deterministic whole-diff classification establishes required review.
- For every completion, retain exact source/PR SHA, trusted gate receipts, all eight existing release gates, focused/full tests, independent review, browser evidence and remaining physical/external acceptance.

## Done when

New Investment-only Control Center is approved, deployed and externally accepted with verified health/rollback receipts, parity, security and mobile QA. If any required observation is unavailable, status stays open.
