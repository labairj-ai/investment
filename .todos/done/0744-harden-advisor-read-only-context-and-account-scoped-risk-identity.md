# Harden Advisor Read-Only Context and Canonical Account-Scoped Risk Identity

- **ID:** 0744
- **Status:** done
- **Created:** 2026-10-14
- **Priority:** high
- **Depends:** 0732, 0734, 0738, 0739, 0741

## Scope and acceptance

- [x] Enforce context reads at SQLite engine level, denying DML/CTE/schema/database mutations; restore prior connection state/callback after success or exception; never commit caller transactions.
- [x] External screener stays mode=ro; no mutable source connections bypass guard; maintain canary stronger write denial.
- [x] Share one canonical risk snapshot: selected account, explicitly ordered positions, risk-relevant orders/fills and selected open intents; identify applicable global policy inputs separately.
- [x] Hash stable semantic state independent of physical insertion order; unrelated-account positions/orders/fills/intents/history do not change risk or authorization identity.
- [x] Scope SELL commitments and canonical brief execution state to selected account; unknown selection remains unavailable, never combines books; preserve portfolio CC coverage source.
- [x] Relevant selected-account changes still invalidate stored decisions; captured and preview identities match; existing price/thesis/lot/CC invalidation remains.
- [x] Inject helper INSERT/UPDATE/DELETE/DDL and CTE writes; test guard restoration and caller transactions, two overlapping accounts, canonical ordering and persistence invalidation.
- [x] Preserve trade arithmetic and execution risk rule behavior; preview creates no trading/audit rows; execution_ready stays false; document selected-account fields.

## QA requirements

- [x] Focused advisor/canary and existing producer Critic tests pass without weakening assertions.
- [x] Full `pytest tests/ -v --tb=short --junitxml=test-results.xml` passes.
- [x] Exact release baseline inventory, TODO consistency and CC behavioral contract gates pass.
- [x] Production-snapshot read-only canary passes with protected state identical.
- [x] Real GitHub Actions passes; completion evidence records results.

## Source

Created from the user’s detailed 2026-10-14 feedback, including its safety, functional, parity, account-scope and compatibility requirements.

## Completion evidence

Completed 2026-10-14 in implementation `ad52bb5`. Focused Advisor tests: 121 passed;
full suite: 2,595 passed, 16 existing skips, no failures. Unchanged producer
fixtures, exact baseline inventory, TODO consistency and CC behavioral contract
gates pass. Real GitHub Actions passed without new waivers:
https://github.com/labairj-ai/investment/actions/runs/38559356644

Production canary v2 receipt: `docs/evidence/advisor-canary-v2-20261014.json`.
Overall health, mutation safety and functional contract all PASS; schema and all
122 existing table identities match before/after. Adaptive BP scenario: captured
100 shares, target 117, expected +17 and observed +17 for both target and delta;
existing policy leaves both BLOCKED, with execution disabled.

Detailed bad-arithmetic/empty-leg/write injections, shared allocation veto parity,
unavailable producer scores/confidence, guard restoration and two-account identity
examples are recorded in `docs/advisor-hardening-qa.md`. Canonical selected-account
risk fields and active equity-rule dependencies are documented there and in
`docs/advisor-decision.md`; no economic scoring or execution rule changes.
