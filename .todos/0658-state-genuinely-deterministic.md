# Make portfolio_state Genuinely Deterministic

- **ID:** 0658
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0653

## Problem

0653 aimed to remove the LLM from `portfolio_state` determination, but `_apply_brief_policy()` still uses `max(normalized_llm_state, floor_state)` via a rank comparison. Because the v4 prompt schema no longer returns `portfolio_state`, the LLM result normalizes to `UNKNOWN` (rank 1), while `STABLE` has rank 0. So a healthy portfolio with only an opportunity or a watch item gets:

```
floor_state = STABLE  (rank 0)
normalized_llm_state = UNKNOWN  (rank 1, absent field)
final = UNKNOWN
```

A healthy opportunity-only or change-only brief produces UNKNOWN — exactly the wrong answer. The ceiling problem is also unsolved: a caller supplying `"URGENT"` with no attention items still produces URGENT.

The correct fix is a pure function:

```python
def _derive_portfolio_state(brief_state: dict) -> str:
    HIGH_SEVERITY = 70
    attention_items = brief_state.get("attention_items", [])
    brief_health = brief_state.get("brief_health", "UNKNOWN")

    if any(item.get("severity", 0) >= HIGH_SEVERITY for item in attention_items):
        return "URGENT"
    elif attention_items:
        return "ATTENTION"
    elif brief_health == "HEALTHY":
        return "STABLE"
    else:
        return "UNKNOWN"
```

`output["portfolio_state"] = _derive_portfolio_state(brief_state)`. Full stop. The LLM output (whatever it contains) has no effect on the authoritative field. `llm_assessed_state` retained for diagnostics.

## Proposed approach

- Extract `_derive_portfolio_state(brief_state)` as a standalone pure function in `portfolio_ai.py`.
- In `_apply_brief_policy()`: remove the rank comparison; call `_derive_portfolio_state(brief_state)` directly; assign to `output["portfolio_state"]`.
- The `policy_overrides` entry should record `{from: llm_assessed_state, to: deterministic_state}` when they differ.
- Remove `_STATE_RANK` dict if it's no longer needed.

Tests using the actual v4 LLM output shape (no `portfolio_state` field in the LLM result):

| brief_health | attention_items | LLM output           | Expected state |
|---|---|---|---|
| HEALTHY | []            | {headline: "..."} no state | STABLE |
| HEALTHY | [] + opportunity | {headline: "..."}   | STABLE |
| HEALTHY | [] + changes  | {headline: "..."}        | STABLE |
| HEALTHY | [severity=50] | {headline: "..."}        | ATTENTION |
| HEALTHY | [severity=80] | {headline: "..."}        | URGENT |
| DEGRADED | []           | {headline: "..."}        | UNKNOWN |
| DEGRADED | [severity=50] | {headline: "..."}       | ATTENTION |
| DEGRADED | [severity=80] | {headline: "..."}       | URGENT |

Also: caller explicitly supplies `"URGENT"` + no attention + HEALTHY → STABLE (ceiling enforced).

## Touches

- `portfolio_ai.py` — extract `_derive_portfolio_state()`; remove rank comparison; `_STATE_RANK` can be deleted
- `tests/` — full 8-row state matrix with v4-shaped LLM output (no `portfolio_state` field); ceiling test

## Done when

- [ ] `_derive_portfolio_state(brief_state)` is a pure function, no LLM input
- [ ] `_apply_brief_policy()` calls it unconditionally; LLM output never affects `portfolio_state`
- [ ] `_STATE_RANK` removed (or no longer used for state selection)
- [ ] `llm_assessed_state` preserved in output for diagnostics
- [ ] Full 8-row state matrix tests pass with v4-shaped LLM output (no `portfolio_state` field)
- [ ] Ceiling test: explicit URGENT from caller + no attention + HEALTHY → STABLE
- [ ] HEALTHY + opportunity only → STABLE (not UNKNOWN)
