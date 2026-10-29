# TODO 0858 — Implement Candidate Workbench, Drilldown and Evidence Timeline

- **ID:** 0858
- **Status:** backlog
- **Created:** 2026-10-29
- **Priority:** high
- **Risk:** L5 (conservative governance/UI boundary; verify against deterministic risk policy)
- **Depends:** 0856, 0857
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Give the owner an auditable, fast way to triage improvement proposals and inspect exact scope, risk, independent review, releases and outcomes without accessing raw logs or modifying source.

## Target files / interfaces

- `dev_agent/dashboard.py (or Investment-owned candidate UI)`
- `dev_agent/store.py (bounded read query only if needed)`
- `tests/test_engineering_control_center.py`
- `scripts/check_development_agent_browser.mjs`

## Scope and acceptance

- [ ] Add server-paged search by title, candidate ID, component with filters for stage, risk, category and source; support value/risk/age sorts with unambiguous unknown values.
- [ ] Each candidate card shows immutable ID, origin/evidence quality, score version, stage, risk reasons, current blocker and latest run/PR disposition; retain L4/L5 risk indicators at all sizes.
- [ ] Detail drawer/bottom sheet presents problem, measurable outcome, source observation, recurrence, frozen plan/criteria, allowed and protected files, TODO dependencies and approved base SHA.
- [ ] Show bounded worktree/run evidence with worker/model identity, iteration/time/action budgets, reviewer findings, validation receipt, linked PR/merge/deployment observation and rollback history.
- [ ] Timeline reconstructs append-only chronological state transitions using real immutable event sequence; negative outcomes are never overwritten or filtered away to imply success.
- [ ] Plan decisions (Approve/Defer/Reject), if surfaced, must call existing authenticated human decision contract; no new trust path. Do not reveal a generic Builder button for L4/L5.
- [ ] Use only trusted HTTPS GitHub links from constrained repository/PR identities; render untrusted model/user text as text, never executable HTML.

## QA and negative acceptance

- [ ] Fixtures cover duplicate titles, colliding IDs, broken links, missing plan, changed SHA, stale review, evidence with script tags, long paths and special characters.
- [ ] Search/pagination deterministic across concurrent events and with >100 candidates; no unbounded initial ledger read.
- [ ] Tests prove unauthorized plan/decision mutation fails and no stale/replayed plan approval can be applied to changed scope/head.
- [ ] Browser test modal/drawer close, deep link, back navigation, no background scroll lock bugs and proper focus restore.
- [ ] Run zero-write assertions on source/financial data plus full release tests.

## Explicit guardrails

- Prioritize evidence-backed improvements, not raw feature count or speculative model scores.
- Scope changes invalidate the frozen approval and require re-planning.
- Do not expose raw prompts, large model logs, financial rows or secrets.

## Global implementation guardrails

- Do not change portfolio/trading/broker code, financial databases or production holdings.
- Do not modify Investment Scout/systemd timers, autonomous activation flags, owner merge/deployment authorities, or existing risk thresholds.
- Do not call or grant access to the separate Qwen Engineering Agent microservice; Investment retains its existing Development Agent.
- Use only exact-head, trusted, independently verifiable evidence; missing/stale/unavailable cannot display as PASS.
- Keep existing single owner Go/No-Go; no additional owner ceremonies, auto-merge, model-issued approvals or deployment actions.
- Treat any source/governance-adjacent change as provisionally L5 until repository deterministic policy evaluates the final diff.

## Done when

Candidate triage and drilldown are complete with immutable evidence linking, deterministic filtering, authenticated optional plan decisions and observed accessibility/negative QA.

**Evidence:** link exact SHA, focused/full suite, all eight established release gates, reviewer outcome, adversarial/browser artifacts and external acceptance state. Checked boxes require real observed evidence, not fixtures or planned work.
