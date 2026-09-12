# Policy Field Enforcement Audit: min_limit_price Rule + Inactive Markers

- **ID:** 0217
- **Status:** backlog
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

`config/trading_policy.json` contains fields that are either absent from `TradingPolicy` class or not enforced by the risk engine. Fields declared in the JSON that look like hard controls but do nothing:
- `execution.min_limit_price: 0.01` — not in `TradingPolicy` class, not enforced
- `risk.max_weekly_loss_pct: 7` — not in `TradingPolicy` class, no weekly-loss rule
- `circuit_breakers.halt_on_position_mismatch: true` — not in `TradingPolicy` class, not enforced
- `circuit_breakers.halt_on_daily_loss_pct: 3` — not in `TradingPolicy` class (distinct from `risk.max_daily_loss_pct`)

A policy field that looks like a hard control but silently does nothing creates false assurance.

## Proposed approach

**Enforce `min_limit_price` (risk rule 19):** Add `min_limit_price()` accessor to `TradingPolicy`. Add risk rule `MIN_LIMIT_PRICE` that fails if `intent.limit_price < policy.min_limit_price()`. Simple, low-risk.

**Mark remaining fields as reserved/future:** In `trading_policy.json`, rename unenforced fields to make their status explicit:
- `max_weekly_loss_pct` → keep, add inline comment `// reserved: enforced in future B0.2 weekly-loss rule`
- `halt_on_position_mismatch` → keep, add comment `// reserved: requires position reconciliation against broker`  
- `halt_on_daily_loss_pct` (circuit_breakers) → keep as-is (it duplicates risk.max_daily_loss_pct intentionally for circuit-breaker separation); document the distinction

**Add policy-coverage test:** `test_policy_fields_enforced_or_documented()` in `tests/test_trade_engine.py` — loads `trading_policy.json`, checks each leaf key against a known-enforced or known-reserved registry, fails if a new key appears that isn't in either list.

## Touches

- `trade_engine/policy.py` — `min_limit_price()` accessor
- `trade_engine/risk_engine.py` — new rule 19 `MIN_LIMIT_PRICE`
- `config/trading_policy.json` — inline comments on reserved fields
- `tests/test_trade_engine.py` — `MIN_LIMIT_PRICE` test, policy-coverage test

## Done when

- [ ] `TradingPolicy.min_limit_price()` returns `execution.min_limit_price` (default 0.01)
- [ ] Risk rule 19 `MIN_LIMIT_PRICE` fails when `intent.limit_price < policy.min_limit_price()`
- [ ] Test: intent with `limit_price=0.001` → REJECTED via MIN_LIMIT_PRICE
- [ ] `trading_policy.json` comments document which fields are reserved/future
- [ ] `test_policy_fields_enforced_or_documented()` passes and would catch new undocumented fields
- [ ] All 391 existing tests still pass
