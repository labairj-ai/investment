# Add Action/Outcome/Validation Schema Consistency Tests

- **ID:** 0132
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0128

## Problem

Similar to the dep-type coverage test added in 0121, there is no automated check that:

1. Every action string that can appear in `executed_actions.action` has an entry in the execution-validation required-fields dict (prevents silent no-op validation for new actions).
2. Every action type handled by the outcome evaluator has an explicit branch in the evaluation model (prevents new actions falling through to a zero-return default silently).
3. Every action eligible for Decision Quality has a documented `outcome_math_version` rationale (prevents contaminated outcomes from entering DQ after future evaluator edits).

These gaps mean that adding a new action type is error-prone: it is possible to write an action, execute it, and have it silently produce wrong outcomes or wrong DQ entries.

## Proposed approach

Write `tests/test_action_coverage.py` with three tests:

**Test 1 — Execution validation coverage:**
- Collect every action string referenced in `agents/*.py` files (regex `"action"\s*:\s*"([A-Z_]+)"` or similar).
- Import the execution-validation required-fields registry.
- Assert that every emitted action has a validation entry. Unknown actions fail loudly.

**Test 2 — Outcome model coverage:**
- Collect every action string (same as above).
- Inspect `_compute_scenarios()` in `outcome_evaluator.py` for handled action types (parse the if/elif/else tree or maintain an explicit `EVALUABLE_ACTIONS` frozenset).
- Assert that every action that is not in `_EXCLUDE_FROM_EVALUATION` (a new constant, analogous to `_EXCLUDE_FROM_DQ`) has an outcome model.

**Test 3 — DQ version coverage:**
- Assert that every action NOT in `_EXCLUDE_FROM_DQ` has a documented `outcome_math_version` assignment in `outcome_evaluator.py` — i.e., the code actually sets `outcome_math_version` on rows for those action types.
- This can be a static check: grep for the action names inside the evaluator code blocks that set `outcome_math_version`.

## Touches

- `tests/test_action_coverage.py` — new file with three consistency tests
- `agents/outcome_evaluator.py` — possibly add `EVALUABLE_ACTIONS` frozenset and `_EXCLUDE_FROM_EVALUATION` constant for test 2
- `agents/decision_quality.py` — `_EXCLUDE_FROM_DQ` already exists; may need export

## Done when

- [ ] `tests/test_action_coverage.py` exists with all three tests
- [ ] Test 1 (validation coverage) passes for all currently emitted actions
- [ ] Test 2 (outcome model coverage) passes: every non-excluded action has an evaluator branch
- [ ] Test 3 (DQ version coverage) passes: every DQ-eligible action has `outcome_math_version` set in evaluator
- [ ] Tests are registered in the standard test suite and pass in CI
