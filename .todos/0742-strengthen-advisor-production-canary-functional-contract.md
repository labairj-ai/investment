# Strengthen Advisor Production Canary Functional Contract

- **ID:** 0742
- **Status:** in-progress
- **Created:** 2026-10-14
- **Priority:** high
- **Depends:** 0740, 0741

## Scope and acceptance

- [ ] Version advisor-canary-v2; report separate mutation_safety and functional_contract; overall PASS requires both.
- [ ] Protect holdings, lots, recommendations, advisor decisions, intents, risk decisions, orders, fills and account state using engine write denial and before/after content identities.
- [ ] Generate stable ticker-independent target/delta scenarios from current finite holdings and marks; independently calculate target minus current shares and preserve explicit quantity. Document fractional shares.
- [ ] Validate supported contract, preview origin, policy vocabulary, structured stages/context identities, no execution authorization, nonempty matching legs and arithmetic equivalence.
- [ ] Report machine-readable failed invariants and captured/target/expected/observed scenario quantities. Missing prerequisites or unexpected pipeline failures must fail functional health.
- [ ] Keep persist=False, allow_llm=False, network/broker/learning-free; denied writes fail mutation safety even when caught; no policy/economic changes.
- [ ] Inject bad arithmetic, empty legs, exceptions, invalid contracts, authorization and INSERT/UPDATE/DELETE/schema writes; validate healthy fixture and production snapshot; record v2 JSON.

## QA requirements

- [ ] Focused advisor/canary and existing producer Critic tests pass without weakening assertions.
- [ ] Full `pytest tests/ -v --tb=short --junitxml=test-results.xml` passes.
- [ ] Exact release baseline inventory, TODO consistency and CC behavioral contract gates pass.
- [ ] Production-snapshot read-only canary passes with protected state identical.
- [ ] Real GitHub Actions passes; completion evidence records results.

## Source

Created from the user’s detailed 2026-10-14 feedback, including its safety, functional, parity, account-scope and compatibility requirements.
