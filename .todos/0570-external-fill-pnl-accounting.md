# Compute and Persist PnL for External and Manual Fills

- **ID:** 0570
- **Status:** backlog
- **Created:** 2026-09-22
- **Priority:** high
- **Depends:** 0568

## Problem

External fills (BROKER_EXTERNAL, MANUAL) currently update position quantity and cash but leave `cost_basis`, `realized_pnl`, and `realized_pnl_pct` NULL on the fills row. The risk engine's MAX_DAILY_LOSS rule is computed as `SUM(-realized_pnl) FROM fills WHERE filled_at >= today` — so a manual or external sell that realizes a large loss correctly drains broker cash and updates holdings but contributes zero to the daily realized-loss circuit breaker. An agent-generated trade that breaches MAX_DAILY_LOSS would halt autonomous submissions; an identical external trade does not. This is a live risk-control blind spot.

## Proposed approach

In the BROKER_EXTERNAL path inside `apply_broker_fill()`, before mutating the position, read the current `avg_cost` from the position row and compute:

- `cost_basis = prior_avg_cost × qty`
- `proceeds = qty × fill_price − fee`
- `realized_pnl = proceeds − cost_basis`
- `realized_pnl_pct = realized_pnl / cost_basis` (guard against divide-by-zero when cost_basis = 0)

Persist those values on the INSERT (or UPDATE if the early-dedup path is reached later). Equity-only scope; the current Alpaca paper policy is equity-only and the adapter prevents option submissions, so options settlement does not need to be generalized.

These fields must be computed before the position row is mutated, since the mutation overwrites `avg_cost`.

## Touches

- `trade_engine/execution_engine.py` — BROKER_EXTERNAL path in `apply_broker_fill()`
- `tests/test_trade_engine.py` — add test: external SELL → fill row has non-NULL `realized_pnl`; assert that value is visible to MAX_DAILY_LOSS query

## Done when

- [ ] An external equity SELL produces a fill row with non-NULL `cost_basis`, `realized_pnl`, and `realized_pnl_pct`
- [ ] `SUM(-realized_pnl)` query used by MAX_DAILY_LOSS includes the external sell's realized loss
- [ ] External BUY fill produces NULL `realized_pnl` (no realized gain/loss on open)
- [ ] No existing tests regress
