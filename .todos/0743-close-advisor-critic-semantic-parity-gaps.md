# Close Advisor Critic Semantic-Parity Gaps

- **ID:** 0743
- **Status:** in-progress
- **Created:** 2026-10-14
- **Priority:** high
- **Depends:** 0737, 0741

## Scope and acceptance

- [ ] Shared review-input contract distinguishes advisor origin, ALLOCATION_CHANGE semantics, unavailable producer score/confidence and authoritative impact/thesis/context references.
- [ ] Reuse shared deterministic layer-target veto for new BUY, ADD, trim and multi-leg reallocation without copying rules or broadening option-specific checks.
- [ ] Advisor LLM prompt explicitly marks missing score/confidence unavailable; no fabricated 50, conviction, strength or producer provenance.
- [ ] Preserve VETO→BLOCKED, CHALLENGE/unavailable→REVIEW_REQUIRED; approval/caution never bypass other gates; deterministic veto cannot call model.
- [ ] Preserve producer fixtures and LLM output schema; advisor excluded from learning; no recommendation, intent, order or fill creation.
- [ ] Corrupt LAYER_TARGETS and prove producer/advisor reason parity; inspect input/prompt; test all verdicts, failure and valid-target paths; record parity examples.

## QA requirements

- [ ] Focused advisor/canary and existing producer Critic tests pass without weakening assertions.
- [ ] Full `pytest tests/ -v --tb=short --junitxml=test-results.xml` passes.
- [ ] Exact release baseline inventory, TODO consistency and CC behavioral contract gates pass.
- [ ] Production-snapshot read-only canary passes with protected state identical.
- [ ] Real GitHub Actions passes; completion evidence records results.

## Source

Created from the user’s detailed 2026-10-14 feedback, including its safety, functional, parity, account-scope and compatibility requirements.
