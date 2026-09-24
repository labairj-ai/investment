# Add Invariant Parameterized Tests for Brief Reliability

- **ID:** 0646
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0644, 0645

## Problem

The current tests verify specific paths (early-return, guardian error, execution error). But the invariant `brief_health != HEALTHY → portfolio_state != STABLE` has many routes to violate it. A single parameterized test suite over all input combinations is more robust than enumerating individual cases — it protects against new code paths silently re-introducing the failure.

## Proposed approach

Write a parameterized test (`pytest.mark.parametrize`) covering every case:

| `brief_health` | items present | LLM outcome | Expected result |
|---|---|---|---|
| HEALTHY | none | — | STABLE allowed |
| DEGRADED | none | — | STABLE forbidden |
| ERROR | none | — | STABLE forbidden |
| ERROR | opportunity | LLM returns STABLE | STABLE forbidden (overridden) |
| ERROR | open decision | LLM returns STABLE | STABLE forbidden |
| ERROR | attention | normal | STABLE forbidden |
| ERROR | items | LLM fails | STABLE forbidden |
| ERROR | items | create_portfolio_brief exception | STABLE forbidden |
| missing brief_health | none | — | STABLE forbidden |
| missing portfolio_state | — | — | UNKNOWN not STABLE |

The property being tested is one invariant, not a collection of individual stories. If any future code path violates the invariant, at least one parametrized case should catch it.

Mock the LLM (`_run_briefing_llm`) to return a controlled `briefing_output` (including STABLE when relevant) and verify the final stored/returned `portfolio_state`.

## Touches

- `tests/test_portfolio_brief.py` — add `@pytest.mark.parametrize` test class or function covering all cases above

## Done when

- [ ] At least 10 parametrized cases covering the combinations in the table above
- [ ] Each case asserts `portfolio_state != "STABLE"` when `brief_health != "HEALTHY"`
- [ ] "LLM returns STABLE despite ERROR" case is included and passes (proves `_enforce_brief_health` fires)
- [ ] "missing brief_health" case is included and treats absence as non-HEALTHY
- [ ] "missing portfolio_state" case proves default is `UNKNOWN` not `STABLE`
