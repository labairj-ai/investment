# TODO 0857 — Build Investment Engineering Overview and Readiness Dashboard

- **ID:** 0857
- **Status:** in-progress
- **Created:** 2026-10-29
- **Priority:** high
- **Risk:** L5 (conservative governance/UI boundary; verify against deterministic risk policy)
- **Depends:** 0856
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Replace the prototype overview with a live, Investment-only entry page that answers: Is the supervised agent ready; what is blocking it; what needs my attention; and when was each status observed?

## Target files / interfaces

- `dev_agent/dashboard.py (or Investment-owned front-end module)`
- `generate_dashboard.py / `serve.py` route navigation where appropriate`
- `tests/test_engineering_control_center.py`
- `scripts/check_development_agent_browser.mjs`

## Scope and acceptance

- [ ] Expose `/engineering/projects/investment` or equivalent Investment-owned route; maintain an explicit link back to the existing Investment dashboard and older `/development-agent` until retirement is separately approved.
- [ ] Hero uses the real supervised admission gate's `READY`/`NOT READY`/`UNAVAILABLE`, rank up to three blocker reasons and link each to diagnostics/evidence. Show source revision and observation time.
- [ ] Display separate summary metrics for active candidates, PRs awaiting actual owner decision, independent validation status, scheduled Scout status and autonomy configuration, explicitly distinguishing planned and observed activity.
- [ ] Render priority work queue cards with candidate ID, category, risk L0–L5, evidence-backed score, source, stage, update age, blocking reason and Inspect action; counts come from a bounded source query.
- [ ] Provide recent activity feed with clear kinds for scheduled Scout, manual runs, fixture activity, owner attestation, validation and deployed observation; never count fixtures as releases.
- [ ] On unavailable, stale, unauthorized or API-error response, render prominent explicit unavailable state, not a green cached summary or zero counts.
- [ ] Keep developer-oriented diagnostics expandable and owner next action simple; no simulated metrics or production-ready claims in live mode.

## QA and negative acceptance

- [ ] Browser contract checks compare displayed readiness/blockers to backend supervised admission fixture and to unavailable-source fixture; no independent frontend readiness computation.
- [ ] Test no candidates/PRs, extremely long titles, missing associated TODO, stale source hash and high-risk L4/L5 warning visibility.
- [ ] Refresh and navigation preserve accessibility focus/readability; all filters and destination links work with keyboard.
- [ ] Test no portfolio data leak and unchanged existing dashboard operational performance; full suite and exact-head CI gates.

## Explicit guardrails

- Never provide an 'Enable autonomy' or 'Run deployment' button.
- Source status labels must distinguish committed configuration from actual OptiPlex runtime.
- Do not treat open PR count or CI success as readiness certification.

## Global implementation guardrails

- Do not change portfolio/trading/broker code, financial databases or production holdings.
- Do not modify Investment Scout/systemd timers, autonomous activation flags, owner merge/deployment authorities, or existing risk thresholds.
- Do not call or grant access to the separate Qwen Engineering Agent microservice; Investment retains its existing Development Agent.
- Use only exact-head, trusted, independently verifiable evidence; missing/stale/unavailable cannot display as PASS.
- Keep existing single owner Go/No-Go; no additional owner ceremonies, auto-merge, model-issued approvals or deployment actions.
- Treat any source/governance-adjacent change as provisionally L5 until repository deterministic policy evaluates the final diff.

## Done when

The Investment overview is source-backed, mobile-responsive, fails visibly on stale evidence and preserves preexisting routes with zero activation changes.

**Evidence:** link exact SHA, focused/full suite, all eight established release gates, reviewer outcome, adversarial/browser artifacts and external acceptance state. Checked boxes require real observed evidence, not fixtures or planned work.

Source implementation and prepared acceptance matrix: `docs/engineering-control-center.md`. Browser fixtures do not close physical-device, live connector, independent review or rollout acceptance. No deployment is authorized.
