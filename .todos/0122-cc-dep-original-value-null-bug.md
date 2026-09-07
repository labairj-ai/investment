# Fix CC Dependency original_value: None — Checker Silently Passes

- **ID:** 0122
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** high
- **Depends:** none

## Problem

Two dependency entries in the CC agent write `original_value: None`, which causes the checker to silently return None (valid) even when the underlying condition has changed.

**Bug 1 — THESIS_VERSION in every SELL_CC recommendation** (`covered_call_agent.py` line 727-731):
```python
{
    "dependency_type": "THESIS_VERSION",
    "dependency_key": ticker,
    "original_value": None,   # ← always None
    ...
}
```
`_check_thesis_version()` does `int(dep["original_value"])` which raises TypeError and returns None. Thesis changes never supersede CC recommendations. The user can update their delta target, strategy, or OTM floor in the thesis and the stale SELL_CC recommendation stays open indefinitely.

**Bug 2 — OPTION_IV in every CC management recommendation** (`covered_call_agent.py` line 421-426, in `_build_cc_mgmt_deps()`):
```python
{
    "dependency_type": "OPTION_IV",
    "dependency_key": ticker,
    "original_value": None,   # ← always None
    ...
}
```
`_check_option_iv_true()` checks `if not stored_iv: return None`. IV collapse never supersedes HOLD_CALL, BUY_TO_CLOSE, or ROLL recommendations.

## Proposed approach

**Bug 1 fix**: Populate `original_value` with the current thesis version integer at rec creation time:
```python
{
    "dependency_type": "THESIS_VERSION",
    "original_value": str(agent_db._get_thesis_version_for_hash(ticker)),
    ...
}
```

**Bug 2 fix**: Populate `original_value` with the current IV from the option snapshot or from the position eval result at management rec creation time:
```python
{
    "dependency_type": "OPTION_IV",
    "original_value": str(round(current_iv_at_rec, 4)) if current_iv_at_rec else None,
    ...
}
```
The management dep builder receives `current_mark` already; the function signature may need to also receive `current_iv`.

## Touches

- `agents/covered_call_agent.py` — SELL_CC dep list (THESIS_VERSION) and `_build_cc_mgmt_deps()` (OPTION_IV)
- `tests/test_dependency_checker.py` — add tests that these deps fire when thesis version increments and when IV drops

## Done when

- [ ] SELL_CC THESIS_VERSION dep has `original_value = str(current_thesis_version)`
- [ ] Management OPTION_IV dep has `original_value = str(current_iv)` (or None only when IV is unavailable)
- [ ] `_check_thesis_version` fires and supersedes a CC rec when thesis version increments
- [ ] `_check_option_iv_true` fires and supersedes a management rec when IV drops > threshold
- [ ] Tests cover both cases with in-memory DB
