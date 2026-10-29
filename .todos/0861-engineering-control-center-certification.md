# TODO 0861 — Implement Technical, Supervised and Autonomy Certification Panels

- **ID:** 0861
- **Status:** backlog
- **Created:** 2026-10-29
- **Priority:** high
- **Risk:** L5 (provisional governance-adjacent; verify with deterministic classifier)
- **Depends:** 0856, 0860; existing certification/rollout contracts 0851–0854
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Separate technical harness certification, real supervised operating history and later autonomy eligibility; do not convert green fixture tests into live authorization.

## Target files / interfaces

- `dev_agent/readiness.py (existing projection reuse)`
- `dev_agent/certification.py (read-only cert adapter)`
- `dev_agent/scheduler_health.py (read-only status adapter)`
- `dev_agent/dashboard.py`
- `tests/test_engineering_control_center.py`

## Scope and acceptance

- [ ] Technical card shows current harness/hash, signed certificate issuance/expiry, validation sandbox/Oracle availability, GitHub effective protection, authenticated production backup metadata, and actual scheduler/system-manager observation.
- [ ] Operational card shows genuine qualified Scout timer slots, verified supervised candidate/release count (minimum 3), distinct healthy deployment observations, and required calendar observation window (minimum 7 days).
- [ ] Fixture/replay/manual Scout runs, CI-only diagnostics, test-only sandbox certificates and duplicate runs cannot contribute real operational credit. Distinguish historical retained evidence from current accepted status.
- [ ] Autonomy card independently displays reviewed configuration, stage (SHADOW/SUPERVISED/LOW-RISK AUTO-PR), `autonomous_implementation`, caps/risk ceiling, kill switch and eligibility; eligible is never synonymous with enabled.
- [ ] Each card displays source, observed/expiry timestamps, exact code hash and blocker reasons with links to source receipt; missing host evidence renders UNAVAILABLE.
- [ ] Rank blockers and link to diagnostic context for 0852 Scout, independent oracle, branch protection, backup, 0853 real pilot, 0854 actual releases without changing their state.
- [ ] Do not implement direct toggle/activation controls; eventual activation remains protected source change with owner Go and live evidence.

## QA and negative acceptance

- [ ] Tests cover 0/3 and 2/3 genuine Scout slots, at least 3 qualifying supervised releases vs duplicated/synthetic ones, 7-day calendar across DST, and stale hash after deployment.
- [ ] Expired or future-dated certificate, missing branch bypass visibility, stale backup, absent Oracle and false source identity render blocked.
- [ ] Ensure observer outage or runtime flag mismatch cannot present READY due to committed config or fixture evidence.
- [ ] Accessibility/browser checks for status labels, collapsed diagnostics and mobile display; full release gates.

## Task-specific guardrails

- Do not start/stop Scout, rewrite systemd timestamps or create acceptance credit from this page.
- Do not alter 0852–0854 acceptance tasks or eligibility thresholds.
- No single click can enable autonomy.

## Common implementation guardrails

- Investment remains exclusively on its existing Development Agent; no integration with the standalone Qwen Engineering Agent service.
- No trading, broker, holdings, financial database, scheduler/systemd, autonomy, risk-threshold or production release changes.
- Keep the existing one owner Go/No-Go decision; no separate model-issued approval, merge, deployment or second owner ceremony.
- Independent exact-SHA validation/receipt authority remains outside candidate-written data; any unavailable, stale or untrusted proof fails closed.
- Re-evaluate final diff against deterministic L0–L5 policy; this backlog is conservatively L5 governance-adjacent.
- Record exact commit SHA, focused/full suite, all eight required release gates, adversarial/browser tests and outstanding external acceptance before closure. Fixture PASS does not prove live readiness.

## Done when

The certification workspace demonstrates independent, source-bound technical, operational and autonomy states with accurate blockers and no ability to self-promote.
