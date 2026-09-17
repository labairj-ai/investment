# Add Schema-Consistency Tests for Action Policy Coverage

- **ID:** 0134
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** high
- **Depends:** none

## Problem

The existing `tests/test_dep_type_coverage.py` catches unregistered `dependency_type` literals by scanning `agents/` at test time. No equivalent guard exists for three analogous coverage gaps: (1) an action emitted by an agent but missing from the execution-validation dispatch, (2) an evaluable action with no outcome model branch, and (3) an action that enters Decision Quality without a trusted `outcome_math_version` assignment. Any new action type can silently slip through all three layers without a test failure.

## Proposed approach

Create `tests/test_schema_consistency.py` following the same regex-scan pattern as `test_dep_type_coverage.py`:

- **Test 1 — action → execution-validation coverage:** Regex-scan `agents/` for emitted `"action"` string literals. Assert every collected action name has a corresponding handler in the execution-validation dispatch (likely in `agents/execution_validator.py` or equivalent).
- **Test 2 — action → outcome model coverage:** Assert every action that can appear in `recommendation_outcomes` has a branch in `outcome_evaluator.py`'s `_compute_scenarios()` or `_compute_cc_management_returns()`. Derive the "known evaluable actions" set from the evaluator's own dispatch constants so the test stays self-maintaining.
- **Test 3 — DQ-eligible action → outcome_math_version trust:** Assert every action *not* in `_EXCLUDE_FROM_DQ` (from `agents/decision_quality.py`) has an `outcome_math_version` assignment in `outcome_evaluator.py`. Prevents a new action from entering Decision Quality statistics with version-0/untagged outcomes.

Open question: should these live in one file (`test_schema_consistency.py`) or be appended to `test_dep_type_coverage.py`? A new file keeps concerns separated and is easier to run in isolation.

## Touches

- `tests/test_schema_consistency.py` (new)
- `tests/test_dep_type_coverage.py` (reference / pattern source, likely no changes)
- `agents/outcome_evaluator.py` lines 48–50 (version constants, read-only)
- `agents/decision_quality.py` lines 38–42 (`_EXCLUDE_FROM_DQ`, read-only)

## Done when

- [ ] `python -m pytest tests/test_schema_consistency.py -v` passes with all three tests green
- [ ] Adding a fake action literal to any agents/ file causes at least one test to fail
- [ ] `python -m pytest tests/` passes with no regressions
