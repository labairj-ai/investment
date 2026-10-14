# Close Advisor Critic Semantic-Parity Gaps

- **ID:** 0743
- **Status:** done
- **Created:** 2026-10-14
- **Priority:** high
- **Depends:** 0737, 0741

## Scope and acceptance

- [x] Shared review-input contract distinguishes advisor origin, ALLOCATION_CHANGE semantics, unavailable producer score/confidence and authoritative impact/thesis/context references.
- [x] Reuse shared deterministic layer-target veto for new BUY, ADD, trim and multi-leg reallocation without copying rules or broadening option-specific checks.
- [x] Advisor LLM prompt explicitly marks missing score/confidence unavailable; no fabricated 50, conviction, strength or producer provenance.
- [x] Preserve VETO→BLOCKED, CHALLENGE/unavailable→REVIEW_REQUIRED; approval/caution never bypass other gates; deterministic veto cannot call model.
- [x] Preserve producer fixtures and LLM output schema; advisor excluded from learning; no recommendation, intent, order or fill creation.
- [x] Corrupt LAYER_TARGETS and prove producer/advisor reason parity; inspect input/prompt; test all verdicts, failure and valid-target paths; record parity examples.

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
