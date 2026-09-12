# Risk Decision Provenance: Persist Policy Hash, Snapshot Refs, Fix UUID Identity

- **ID:** 0204
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

Two related issues:

1. `risk_decisions` table stores who approved the trade and when, but not *which policy version* authorized it or what the account/market state was at evaluation time. Five years from now it will be impossible to reconstruct "why was this allowed?"

2. `risk_decisions` uses `INTEGER PRIMARY KEY AUTOINCREMENT` for `decision_id`, but `_finalize()` generates a UUID and returns it in the `RiskDecision` object without storing it as the DB identity. The in-memory object and the DB row use different identity schemes — the UUID returned by `_finalize()` is not persisted anywhere.

## Proposed approach

**Fix `decision_id` to UUID:**
- Change `risk_decisions.decision_id` from `INTEGER PRIMARY KEY AUTOINCREMENT` to `TEXT PRIMARY KEY`
- `_finalize()` stores the UUID as the PK
- `RiskDecision.decision_id` matches the DB row exactly

**Add provenance columns to `risk_decisions`:**
```sql
policy_version       TEXT
policy_hash          TEXT   -- 12-char SHA256 of trading_policy.json at evaluation time
account_cash_at_eval REAL   -- account.current_cash when risk was evaluated
account_nav_at_eval  REAL   -- NAV (cash + position value) at evaluation time
```

**Update `evaluate()` signature** to pass `policy` through to `_finalize()`:
```python
def _finalize(intent_id, checks, conn, policy, account, nav) -> RiskDecision:
```

**TradeIntent** already has `strategy_config_hash`; add `policy_hash` field too (set by IntentBuilder from `policy.policy_hash()`).

**Audit chain** for any fill:
```
Recommendation
  → TradeIntent (recommendation_id, strategy_config_hash, policy_hash)
  → RiskDecision (policy_version, policy_hash, account_cash_at_eval)
  → Order (intent_id)
  → Fill (order_id, cost_basis, realized_pnl)
```

## Touches

- `agent_db.py` — alter `risk_decisions`: TEXT PK, add provenance columns; alter `trade_intents`: add `policy_hash`
- `trade_engine/risk_engine.py` — `_finalize()` writes provenance; pass policy + account into it
- `trade_engine/models.py` — `RiskDecision.decision_id` must match DB PK (TEXT UUID)
- `trade_engine/intent_builder.py` — set `policy_hash` on TradeIntent

## Done when

- [ ] `risk_decisions.decision_id` is TEXT (UUID), matching `RiskDecision.decision_id` returned by `_finalize()`
- [ ] `risk_decisions` has `policy_version`, `policy_hash`, `account_cash_at_eval`, `account_nav_at_eval`
- [ ] `trade_intents` has `policy_hash` set by IntentBuilder
- [ ] Test: round-trip a risk decision; DB row `decision_id` == returned `RiskDecision.decision_id`
- [ ] Test: `policy_hash` in risk_decisions matches `TradingPolicy.policy_hash()` at evaluation time
