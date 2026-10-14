# Strengthen Advisor Production Canary Functional Contract

- **ID:** 0742
- **Status:** done
- **Created:** 2026-10-14
- **Priority:** high
- **Depends:** 0740, 0741

## Scope and acceptance

- [x] Version advisor-canary-v2; report separate mutation_safety and functional_contract; overall PASS requires both.
- [x] Protect holdings, lots, recommendations, advisor decisions, intents, risk decisions, orders, fills and account state using engine write denial and before/after content identities.
- [x] Generate stable ticker-independent target/delta scenarios from current finite holdings and marks; independently calculate target minus current shares and preserve explicit quantity. Document fractional shares.
- [x] Validate supported contract, preview origin, policy vocabulary, structured stages/context identities, no execution authorization, nonempty matching legs and arithmetic equivalence.
- [x] Report machine-readable failed invariants and captured/target/expected/observed scenario quantities. Missing prerequisites or unexpected pipeline failures must fail functional health.
- [x] Keep persist=False, allow_llm=False, network/broker/learning-free; denied writes fail mutation safety even when caught; no policy/economic changes.
- [x] Inject bad arithmetic, empty legs, exceptions, invalid contracts, authorization and INSERT/UPDATE/DELETE/schema writes; validate healthy fixture and production snapshot; record v2 JSON.

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
