# Remove Hard-Coded Layer Targets from NO ACTION Hashing

- **ID:** 0097
- **Status:** done
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

`_compute_no_action_state_extras()` in `agents/orchestrator.py` contains a hard-coded `_LAYER_TARGETS = {1: 50.0, 2: 30.0, 3: 20.0}` — an old three-layer portfolio model. The actual strategy uses a five-layer model defined in `strategy_config.LAYER_TARGETS`. This means the Guardian's NO_ACTION deduplication hash is computed against stale targets, so changes in the real layer targets (or drift relative to the real targets) do not correctly invalidate cached NO_ACTION records.

## Proposed approach

- Delete the local `_LAYER_TARGETS` dict inside `_compute_no_action_state_extras()`
- Import and use `from strategy_config import LAYER_TARGETS` instead
- Add a test that asserts there is exactly one definition of layer targets in the codebase (grep-based or import-based), so this class of bug cannot silently re-appear
- Verify that the `strategy_config.LAYER_TARGETS` values match what the Guardian agent actually uses for drift calculations

## Touches

- `agents/orchestrator.py`
- `strategy_config.py` (read-only, just to confirm the canonical source)
- `tests/` (new single-source-of-truth assertion test)

## Done when

- [ ] `_compute_no_action_state_extras()` references `strategy_config.LAYER_TARGETS`, not a local dict
- [ ] No other file in `agents/` defines its own copy of layer targets
- [ ] Test asserts that importing `agents.orchestrator` and `strategy_config` yields the same layer target values
- [ ] `pytest` passes after the change
- [ ] Regression: Guardian NO_ACTION hash changes when `strategy_config.LAYER_TARGETS` changes (verified manually or by test)
