# Harden Advisor Read-Only Context and Canonical Account-Scoped Risk Identity

- **ID:** 0744
- **Status:** in-progress
- **Created:** 2026-10-14
- **Priority:** high
- **Depends:** 0732, 0734, 0738, 0739, 0741

## Scope and acceptance

- [ ] Enforce context reads at SQLite engine level, denying DML/CTE/schema/database mutations; restore prior connection state/callback after success or exception; never commit caller transactions.
- [ ] External screener stays mode=ro; no mutable source connections bypass guard; maintain canary stronger write denial.
- [ ] Share one canonical risk snapshot: selected account, explicitly ordered positions, risk-relevant orders/fills and selected open intents; identify applicable global policy inputs separately.
- [ ] Hash stable semantic state independent of physical insertion order; unrelated-account positions/orders/fills/intents/history do not change risk or authorization identity.
- [ ] Scope SELL commitments and canonical brief execution state to selected account; unknown selection remains unavailable, never combines books; preserve portfolio CC coverage source.
- [ ] Relevant selected-account changes still invalidate stored decisions; captured and preview identities match; existing price/thesis/lot/CC invalidation remains.
- [ ] Inject helper INSERT/UPDATE/DELETE/DDL and CTE writes; test guard restoration and caller transactions, two overlapping accounts, canonical ordering and persistence invalidation.
- [ ] Preserve trade arithmetic and execution risk rule behavior; preview creates no trading/audit rows; execution_ready stays false; document selected-account fields.

## QA requirements

- [ ] Focused advisor/canary and existing producer Critic tests pass without weakening assertions.
- [ ] Full `pytest tests/ -v --tb=short --junitxml=test-results.xml` passes.
- [ ] Exact release baseline inventory, TODO consistency and CC behavioral contract gates pass.
- [ ] Production-snapshot read-only canary passes with protected state identical.
- [ ] Real GitHub Actions passes; completion evidence records results.

## Source

Created from the user’s detailed 2026-10-14 feedback, including its safety, functional, parity, account-scope and compatibility requirements.
