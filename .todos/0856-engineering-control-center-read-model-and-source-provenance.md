# TODO 0856 — Implement Investment-Owned Read Model and Provenance Contract

- **ID:** 0856
- **Status:** in-progress
- **Created:** 2026-10-29
- **Priority:** critical
- **Risk:** L5 (conservative governance/UI boundary; verify against deterministic risk policy)
- **Depends:** existing development ledger, `dev_agent/dashboard.py`, `dev_agent/readiness.py`; no new activation prerequisites
- **Source:** `docs/plans/engineering-control-center-investment-v2.md`

## Problem and objective

Create a bounded, authenticated, Investment-owned presentation read model for the new Engineering Control Center without changing the existing agent, ledger, owner gateway or release path. Replace prototype sample data with authoritative projections only.

## Target files / interfaces

- `dev_agent/dashboard.py`
- `dev_agent/readiness.py`
- `dev_agent/store.py (read interfaces only, if required)`
- `serve.py (read-only route registration)`
- `tests/test_development_agent.py`
- `tests/test_engineering_control_center.py (new)`

## Scope and acceptance

- [ ] Define a versioned DTO with `status`, `reason_code`, `reason_summary`, `source`, `observed_at`, optional `expires_at`, `policy_version`, `repository`, `head_sha`, `receipt_id`, and `verifier_status` for every readiness/gate judgment.
- [ ] Add Investment-only read endpoints under `/api/engineering/v1/projects/investment/` for overview, candidates, candidate detail, PRs, validation, certification and audit, or document a safer equivalent route within existing `serve.py`.
- [ ] Read canonical candidate/event/owner records from the dedicated `development-control.sqlite3` ledger; never query trading or portfolio tables for this UI. Reuse existing readiness/acceptance projections rather than reconstructing readiness in JavaScript.
- [ ] Enforce existing authenticated reader, same-origin, and server-side identity boundaries; do not send `DEV_AGENT_API_TOKEN`, owner credentials, signing keys or provider secrets to browser content or query arguments.
- [ ] Implement deterministic pagination, allowlisted filters, sorting, bounded page size/payload size, redaction and schema validation. Read-only GETs must never write ledger/scheduler/host state.
- [ ] Return source freshness and explicit `UNAVAILABLE`/`STALE` when observer, GitHub, oracle, certification or ledger evidence is missing; do not substitute committed config, mock data or cached success for observed operational state.
- [ ] Provide a migration-compatible adapter for existing `/api/development-agent`; keep existing consumers functional and expose no arbitrary code/command or activation API.

## QA and negative acceptance

- [ ] Focused contract tests cover populated/empty ledger, missing event links, future timestamps, expired certificates, partial CI, stale SHA, unknown enum, oversized fields and pagination boundaries.
- [ ] Verify every GET leaves ledger bytes/events and protected financial state unchanged (negative mutability tests); malformed queries return bounded safe errors.
- [ ] Test reader denied without credentials, forbidden cross-origin, malicious project IDs, stale cached GET and attempted injection/secret fields; never return data from another project.
- [ ] Confirm source-derived technical readiness is distinct from owner PR decision, current GitHub CI and deployed health; test all unavailable cases.
- [ ] Run existing Development Agent focused tests, TODO consistency and full eight release gates at the exact PR head.

## Explicit guardrails

- Never widen user permissions or add a GitHub write token to the reader.
- Cache only explicitly time-bounded, source-labeled read projections; never cache an owner approval as new authority.
- Treat Investment exclusion from the standalone engineering-agent as mandatory.

## Global implementation guardrails

- Do not change portfolio/trading/broker code, financial databases or production holdings.
- Do not modify Investment Scout/systemd timers, autonomous activation flags, owner merge/deployment authorities, or existing risk thresholds.
- Do not call or grant access to the separate Qwen Engineering Agent microservice; Investment retains its existing Development Agent.
- Use only exact-head, trusted, independently verifiable evidence; missing/stale/unavailable cannot display as PASS.
- Keep existing single owner Go/No-Go; no additional owner ceremonies, auto-merge, model-issued approvals or deployment actions.
- Treat any source/governance-adjacent change as provisionally L5 until repository deterministic policy evaluates the final diff.

## Done when

A read-only Investment API returns complete source-labeled bounded data, existing dashboard API remains compatible and independent tests prove no authority/data mutation.

**Evidence:** link exact SHA, focused/full suite, all eight established release gates, reviewer outcome, adversarial/browser artifacts and external acceptance state. Checked boxes require real observed evidence, not fixtures or planned work.

Implementation source: `dev_agent/control_center.py`; API contract and open external acceptance: `docs/engineering-control-center.md`. Source tests do not close live acceptance.
