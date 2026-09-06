# Fix Dependency Re-evaluation to Use Full Portfolio Snapshot

- **ID:** 0043
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0037

## Problem

When `_trigger_reeval()` in `dependency_checker.py` fires after a recommendation is superseded, it builds a `PortfolioSnapshot` where every holding has `shares=0, avg_cost=0, market_value=0, weight_pct=0` — only `current_price` is populated from `holding_day`. Any agent that re-runs against this snapshot and reads `weight_pct` (Sell/Trim P-score), `market_value` (Guardian NAV impact), or `avg_cost` (tax calculations) will produce garbage or zero scores. This makes re-evaluated recommendations unreliable.

## Proposed approach

- Replace the manual snapshot assembly in `_trigger_reeval()` with a call to `build_portfolio_snapshot()` (0037).
- Pass the triggering ticker via context so single-ticker agents can filter if needed.
- Verify `build_portfolio_snapshot()` is fast enough to call on re-eval (it reads live DB + CSV, should be sub-second).

## Touches

- `agents/dependency_checker.py` (`_trigger_reeval`)
- Depends on `build_portfolio_snapshot()` from 0037

## Done when

- [x] `_trigger_reeval()` calls `build_portfolio_snapshot()` instead of assembling a partial snapshot
- [x] Re-evaluated Sell/Trim recommendations have correct `weight_pct` and `avg_cost` in `action_payload`
- [x] Re-evaluated CC recommendations have correct `market_value` for the ticker
- [x] No `shares=0` holding snapshot reaches an agent during a re-eval cycle
- [x] **Backend QA:** already live on optiplex since 0037 landed
- [x] **Frontend QA:** no change to API surface
- [x] **No service regression:** no change deployed

## Outcome

Already resolved by 0037. `agents/dependency_checker.py` line 89–92 imports and calls `build_portfolio_snapshot()` from `agents/snapshot.py`, which reads `shares` + `avg_cost` from `holdings.csv` and `current_price` / `market_value` / `weight_pct` from `holding_day`. The partial-snapshot bug described in the Problem never reached production — the canonical builder was wired in when 0037 implemented `agents/snapshot.py`. No code changes needed for this item.
