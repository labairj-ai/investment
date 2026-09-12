# Recommendation-Driven Position Sizing: Agent Proposes, Policy Enforces Ceiling

- **ID:** 0207
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0195

## Problem

`IntentBuilder.build_intent()` currently sizes every approved BUY to `min(max_new_position_pct, max_single_position_pct)` — the policy maximum. This conflates two responsibilities:

- **Investment intelligence**: "I want a 2.5% ANET position"
- **Risk policy**: "You may not exceed 5% in a new position"

Every approved BUY is automatically sized at the policy ceiling, regardless of what the agent actually wanted. This makes it impossible to measure whether agent sizing decisions create alpha — they're all overridden to the same maximum.

## Proposed approach

Agents should emit their desired size in `action_payload_json`:
```json
{
  "price": 142.44,
  "target_weight_pct": 2.5
}
```
or:
```json
{
  "price": 142.44,
  "quantity": 7
}
```

**IntentBuilder sizing logic:**
```python
if payload.get("quantity"):
    quantity = int(payload["quantity"])
elif payload.get("target_weight_pct"):
    target_dollars = nav * payload["target_weight_pct"] / 100
    quantity = floor(target_dollars / limit_price)
else:
    # Fallback: use max_new_position_pct (current behavior, preserved for backward compat)
    target_dollars = nav * policy.max_new_position_pct() / 100
    quantity = floor(target_dollars / limit_price)
```

**Risk engine** remains the ceiling enforcer: if the proposed quantity would exceed `max_single_position_pct` or `max_new_position_pct`, the intent is REJECTED (not silently clamped). The agent must re-recommend with a lower size.

**Existing recommendations** without `target_weight_pct` fall through to the current fallback — backward compatible.

This also applies to TRIM: the agent already emits `trim_fraction` in payload — that pattern is correct and should be the template for BUY.

## Touches

- `trade_engine/intent_builder.py` — read `target_weight_pct` or `quantity` from payload; fallback to current behavior when absent
- `agents/sell_trim_agent.py` (and future buy agents) — add `target_weight_pct` to `action_payload_json`
- `tests/test_trade_engine.py` — test: rec with `target_weight_pct=2.5%` → intent sized at 2.5%, not 5%

## Done when

- [ ] IntentBuilder reads `quantity` from payload if present, uses it directly
- [ ] IntentBuilder reads `target_weight_pct` from payload if present, sizes accordingly
- [ ] Fallback to `max_new_position_pct` when neither field is present (backward compat)
- [ ] Risk engine still rejects if proposed size exceeds policy limit (not silently clamped)
- [ ] Test: `target_weight_pct=2.5` on $10k NAV @ $100 price → quantity=24 (not 49 from 5% max)
