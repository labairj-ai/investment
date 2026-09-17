# Intent Builder: Recommendation → TradeIntent for BUY/TRIM/EXIT

- **ID:** 0195
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** 0191, 0192

## Problem

An accepted recommendation does not automatically become a trade. The Intent Builder is the bridge: it reads a closed recommendation, validates that the recommendation is actually executable in the agentic account (not the reference portfolio), computes quantity/sizing for the target account, constructs a `TradeIntent` with full provenance linkage, and writes it to `trade_intents`.

This is the only place recommendations flow into the execution path. Nothing else creates TradeIntents.

## Proposed approach

**`trade_engine/intent_builder.py`**

```python
def build_intent(
    recommendation_id: int,
    account_id: str,
    policy: TradingPolicy,
) -> TradeIntent | None:
```

Procedure:
1. Load recommendation row. Validate: status=ACCEPTED, action in {BUY, TRIM, EXIT}, not expired.
2. Load ticker, current price, account cash + positions from DB.
3. **Sizing logic** (for BUY):
   - Target weight = min(policy.max_new_position_pct, policy.max_single_position_pct − current_weight)
   - Quantity = floor((account_NAV × target_weight / 100) / current_price)
   - Minimum: 1 share. If quantity < 1 → return None (position too small to open).
4. **Sizing logic** (for TRIM):
   - Read `trim_fraction` from recommendation's `action_payload`.
   - Quantity = floor(current_position × trim_fraction). If 0 → None.
5. **Sizing logic** (for EXIT):
   - Quantity = current_position (full exit).
   - If no position in agentic account → return None.
6. Set `limit_price`:
   - Use recommendation's `action_payload.price` if present, else live bid/ask mid.
   - For BUY: limit = ask × (1 + max_slippage_pct). For SELL: limit = bid × (1 − max_slippage_pct).
7. Set `valid_until` = market close today (or next trading day if outside hours).
8. Link provenance: `recommendation_id`, `agent_run_id` (from rec's agent_run_id FK), `thesis_version`, `strategy_config_hash`.
9. Write intent to `trade_intents` table with status=PENDING.
10. Return the `TradeIntent`.

**Not supported yet** (intentionally deferred):
- SELL_CC / BUY_TO_CLOSE / ROLL_* (covered calls need underlying shares first)
- Allocating from the reference portfolio
- Multi-leg orders

## Touches

- `trade_engine/intent_builder.py`
- `agent_db.py` — read current position for agentic account (position_snapshots), account cash

## Done when

- [ ] BUY recommendation → TradeIntent with correct quantity (target weight sizing)
- [ ] TRIM recommendation → TradeIntent with quantity = position × trim_fraction
- [ ] EXIT recommendation → TradeIntent with quantity = full current position
- [ ] Recommendation with action=SELL_CC → returns None (not yet supported)
- [ ] Recommendation for ticker not in agentic account → EXIT returns None (no position)
- [ ] BUY sizing: quantity = 0 when price × min_shares > available capital → returns None
- [ ] Intent written to trade_intents with correct recommendation_id, thesis_version, config_hash
- [ ] Duplicate call for same recommendation_id → returns existing intent (idempotent)
- [ ] Tests for each action type and edge case
