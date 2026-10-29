# TODO 0863 — Harden Mobile UX, Accessibility and UI Security

- **ID:** 0863
- **Status:** in-progress
- **Created:** 2026-10-29
- **Priority:** high
- **Risk:** L5 (conservative; verify via deterministic whole-diff policy)
- **Depends:** 0857, 0858, 0859, 0860, 0861, 0862
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Provide a reliable mobile-first experience for reviewing Investment engineering decisions, not simply a scaled desktop page. Ensure high-risk warnings and blocked Go reasons remain visible on a phone.

## Target files / interfaces

- `dev_agent/dashboard.py (Investment UI CSS/JS)`
- `scripts/check_development_agent_browser.mjs`
- `tests/test_engineering_control_center.py`
- `docs/plans/engineering-control-center-investment-v2.md (acceptance reference)`

## Scope and acceptance

- [ ] Desktop has six destinations: Overview, Candidates, PRs, Validation, Certification and Audit. Mobile fixed navigation has Home, Queue, PRs, Gates, More (Certification/Audit) with safe-area padding.
- [ ] At 320/360/390/430/768/1280/1440 CSS px, no horizontal document overflow, clipped SHA, unreadable table or obstructed action; use responsive cards with progressive disclosure.
- [ ] Candidate details and PR review open as desktop side drawers and mobile bottom sheets; preserve back navigation, visible focus, close/Escape behavior and scroll context.
- [ ] Tap targets >=44×44 CSS px, no hover-only interactions, logical tab/heading order, accessible names, WCAG AA text contrast, reduced-motion respect and error announcement in live region.
- [ ] Risk L4/L5 warning, evidence freshness, failed gate and Go disabled reason stay visible before action, never concealed solely for layout economy.
- [ ] Do not invoke Go/No-Go on swipe, row selection, accidental double tap or dialog close; use deliberate second confirmation within existing owner's one-decision workflow.
- [ ] Use strict text rendering/sanitization/CSP and HTTPS GitHub allowlist; no exposed credentials or mutable sample/fake production data.

## QA requirements and negative paths

- [ ] Automated browser tests on all required viewports with long titles, 40-char SHAs, huge failures, escaped HTML, no candidates, paused status, untrusted evidence and latency failures.
- [ ] Keyboard-only screen flow, focus trapping/restoration, Escape, screen-reader announcement, reduced-motion and color-independent status tests.
- [ ] Physical Android and iPhone touch/VoiceOver/TalkBack acceptance remains open until observed; document devices/OS/browser/screenshots and findings rather than claiming simulator PASS.
- [ ] Security tests for clickjacking/CSP, CSRF on owner actions, token leakage, malicious external links and stale Go preview; performance/large queue no hangs.
- [ ] Exact-head focused/full tests, browser suite and all eight release gates pass.

## Task-specific guardrails

- Do not duplicate UI business logic by device class; one state model, responsive presentation.
- Do not relax owner authentication or introduce unsafe standalone browser credentials for mobile.
- No cosmetic PASS on physical device testing without genuine observations.

## Non-negotiable boundaries

- Investment continues to use its own Development Agent and trusted single-owner Go/No-Go gateway, with no dependency on the separate Qwen microservice.
- No change to live portfolio/broker data, policy thresholds, Scout timers, validators, Oracle authority, credential owners, autonomy settings or deployment service solely for dashboard delivery.
- Distinguish committed config/source tests from live host acceptance and exact-SHA authoritative evidence; unknown/unavailable/stale remains blocked.
- This is governance-adjacent L5 planning until deterministic whole-diff classification establishes required review.
- For every completion, retain exact source/PR SHA, trusted gate receipts, all eight existing release gates, focused/full tests, independent review, browser evidence and remaining physical/external acceptance.

## Done when

Desktop and mobile meet viewport, accessibility, security and physical device acceptance; no displayed blocker or authority step disappears at narrow widths.

Source implementation and prepared acceptance matrix: `docs/engineering-control-center.md`. Browser fixtures do not close physical-device, live connector, independent review or rollout acceptance. No deployment is authorized.
