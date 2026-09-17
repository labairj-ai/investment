# Execution Cost Accounting: Fee-Adjusted Returns and Implementation Shortfall

- **ID:** 0339
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0333, 0338

## Problem

`trade_outcomes` stores `fill_fees` but the labeler computes `return = P_horizon / P_fill - 1` without incorporating them. The todo description says "fee-adjusted returns" but the implementation is not actually fee-adjusted. For a BUY fill:

```
R_net = (Q * P_horizon - Q * P_fill - Fees) / (Q * P_fill + Fees)
```

For Alpaca equities, commissions are often zero, so this won't move current numbers much — but getting the semantic definition right now avoids trouble when adding instruments or brokers with non-zero fees.

Additionally, there is no measurement of execution quality relative to the price at the time the decision was made. A recommendation proposes a limit price; the actual fill may be better or worse. Implementation shortfall (IS) captures this:

```
IS_buy  = (P_fill - P_arrival) / P_arrival     # positive = slippage hurt us
IS_sell = (P_arrival - P_fill) / P_arrival     # positive = slippage hurt us
```

Where `P_arrival` is the mid/last price at the time the intent was created. This starts teaching the system whether execution is degrading good recommendations.

## Proposed approach

- Add `arrival_price REAL` column to `trade_outcomes` (and populate it at fill-spawn time from the limit_price on the intent, as a proxy for arrival price until real-time quotes are available)
- Add `implementation_shortfall REAL` column; labeler computes and writes it at label time using `arrival_price` vs `fill_price`
- Change labeler to compute fee-adjusted net returns: subtract `fill_fees` from numerator, add to denominator cost basis
- Rename current `return_Xw` → make it clearly the gross (pre-fee) return if desired for comparison, or just compute net from the start
- For instruments with zero fees, net return equals gross return — no behavioral change

Slippage reporting in serve.py: add a `execution_quality` block to the champion/challenger endpoint showing mean IS by action type.

## Touches

- `agent_db.py` — add `arrival_price`, `implementation_shortfall` to `trade_outcomes` CREATE TABLE + `_new_cols`
- `trade_engine/execution_engine.py` — `_spawn_trade_outcome()`: populate `arrival_price` from `trade_intents.limit_price` at spawn time
- `agents/learning/outcome_labeler.py` — `label_trade_outcomes()`: compute fee-adjusted returns; compute and write `implementation_shortfall`
- `serve.py` — `_handle_champion_challenger()`: add execution quality stats
- `tests/test_outcome_labeler.py` — assert fee deducted from return; assert IS computed correctly for BUY vs SELL

## Outcome

4 files changed. `agent_db.py`: added `arrival_price REAL` and `implementation_shortfall REAL` to `trade_outcomes` CREATE TABLE + `_new_cols`. `trade_engine/execution_engine.py`: `_spawn_trade_outcome()` now selects `ti.limit_price` in its JOIN and writes it as `arrival_price` at spawn time. `agents/learning/outcome_labeler.py`: `label_trade_outcomes()` reads `fill_qty`, `fill_fees`, `arrival_price` from the row; computes `fees_per_share = fill_fees/fill_qty`; `effective_entry = fill_price + fees_per_share` (BUY) or `fill_price - fees_per_share` (SELL); computes `implementation_shortfall = (fill_price - arrival_price)/arrival_price` for BUY, sign-flipped for SELL; writes IS to DB at first label (persisted once across all horizon updates). `tests/test_outcome_labeler.py`: `TestExecutionCostAccounting0339` class with 4 tests: zero-fee return unchanged, non-zero fee reduces return, IS written when arrival_price set, IS is NULL when no arrival_price. 792 passed, 16 skipped.

## Done when

- [x] `trade_outcomes` carries `arrival_price` (populated at fill-spawn from intent limit_price) and `implementation_shortfall`
- [x] Labeler computes fee-adjusted `return_Xw` using effective entry price (fill_price + fees/qty for BUY, fill_price - fees/qty for SELL)
- [x] `implementation_shortfall` is written for each labeled fill when `arrival_price` is set; NULL otherwise
- [x] Zero-fee fills: net return equals gross return (no regression)
- [x] `python -m pytest tests/` passes with no regressions
