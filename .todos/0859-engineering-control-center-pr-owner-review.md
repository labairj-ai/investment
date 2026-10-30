# TODO 0859 — Build PR Review and Existing Owner Go/No-Go Experience

- **ID:** 0859
- **Status:** backlog
- **Created:** 2026-10-29
- **Priority:** critical
- **Risk:** L5 (provisional governance-adjacent; verify with deterministic classifier)
- **Depends:** 0856, 0860; existing approved owner-side gateway and branch rules
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Deliver a concise, trustworthy PR review screen while keeping all real approval and merge authority with the already established single-owner gateway. The browser may recommend/preview only and must not become a new approval principal.

## Target files / interfaces

- `dev_agent/dashboard.py (PR view only)`
- `dev_agent/github.py (read-only PR metadata adapter only, if required)`
- `owner_gateway/* (no modifications unless separate reviewed security scope)`
- `docs/solo-owner-governance.md (reference, not a change request)`
- `tests/test_development_agent.py`
- `tests/test_engineering_control_center.py`

## Scope and acceptance

- [ ] PR list shows exact repository, base branch/SHA, head SHA, linked candidate IDs, changed file inventory, deterministic risk, Reviewer result, GitHub CI, independent Oracle verification, effective protection and owner disposition.
- [ ] Distinguish repository CI GREEN from trusted oracle PASS and from release/owner-Go eligibility. Show `STALE` whenever source or head differs and invalidate prior presentation/approval.
- [ ] Review sheet displays current immutable SHA, changed protected surfaces, diff/CI links, validation blockers, financial/execution consequences for L4/L5 and any necessary rationale, without asking the owner to copy a hash.
- [ ] UI affords single Go / No-Go only through isolated owner-side authenticated connector; existing `go_no_go` remains the only authority. No browser-held GitHub owner/deployer token, no direct merge endpoint and no competing approval ledger.
- [ ] Gateway verifies owner GitHub ID/login, exact current head, risk, policy, CI and independent evidence and rechecks on action; changed head or revocation refuses and requires fresh review, nonce generated server-side.
- [ ] After Go, show distinct real states for accepted decision, pending CI, expected-SHA merge, merged-main CI, deployment admission and delayed HEALTHY/FAILED observation. Do not report deployment success from a Go receipt.
- [ ] No-Go halts continuation and records disposition without source mutation; if a PR is not eligible, disable Go with reason and allow inspection.
- [ ] Maintain absolute separation between dashboard display, owner authorization object, and fixed deployment controller credentials.

## QA and negative acceptance

- [ ] Adversarial scenarios: head change between render/click, duplicate click, replay nonce, simultaneous Go/No-Go, older Go superseded by No-Go, forged actor, wrong repo and missing protected risk acknowledgements.
- [ ] Unavailable GitHub branch protection, stale CI, missing Oracle receipt or failed reviewer yields blocked Go, not optimistic UI.
- [ ] Test owner-only action routing; arbitrary read-only viewer/Scout/Builder/Reviewer cannot send approval or access owner credentials.
- [ ] Physical/mobile review confirmation, focus trap, disabled reason announcement and accidental-tap protection.
- [ ] Existing owner gateway tests must remain green; full release gates pass; no merge/deploy attempted during UI QA.

## Task-specific guardrails

- The design is *not* permission to install/configure or change the owner gateway.
- Never add a second approval step for the same release.
- Live Go integration must remain disabled until explicitly accepted on host.

## Common implementation guardrails

- Investment remains exclusively on its existing Development Agent; no integration with the standalone Qwen Engineering Agent service.
- No trading, broker, holdings, financial database, scheduler/systemd, autonomy, risk-threshold or production release changes.
- Keep the existing one owner Go/No-Go decision; no separate model-issued approval, merge, deployment or second owner ceremony.
- Independent exact-SHA validation/receipt authority remains outside candidate-written data; any unavailable, stale or untrusted proof fails closed.
- Re-evaluate final diff against deterministic L0–L5 policy; this backlog is conservatively L5 governance-adjacent.
- Record exact commit SHA, focused/full suite, all eight required release gates, adversarial/browser tests and outstanding external acceptance before closure. Fixture PASS does not prove live readiness.

## Done when

PR review shows complete exact-head evidence and only the current trusted owner connector can accept Go/No-Go; replay, head drift and insufficient evidence demonstrably fail closed.
