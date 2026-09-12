# Contract-Weighted BTC and Roll Execution Aggregation

- **ID:** 0185
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

Three related execution-accounting bugs in `aggregate_executions()` and `_resolve_chain()`:

**1. BUY_TO_CLOSE not aggregated** — `aggregate_executions()` has no branch for `BUY_TO_CLOSE`. It falls to the `else` path which sums `quantity` (None for BTC → 0), returning `weighted_avg_price = 0`. This means `exec_rec.get("execution_price")` is always 0 for standalone BTC recommendations. `_resolve_chain()` works around this by reading raw fills directly, but that introduces the next bug.

**2. Unweighted BTC average in `_resolve_chain()`** — The terminal BTC accumulation does:
```python
terminal_btc = sum(btc_prices) / len(btc_prices)  # unweighted!
```
For a 4-contract position closed in two fills (1 contract @ $2, 3 contracts @ $4), this gives $3 but the correct contract-weighted average is $3.50. At 3× scale the error is material.

**3. Unweighted ROLL leg aggregation** — The ROLL branch sums raw prices:
```python
btc_debit   = sum(float(e.get("execution_price") or 0) for e in btc_legs)
sto_premium = sum(float(e.get("premium") or ...) for e in sto_legs)
```
For a single-leg roll (one BTC fill + one STO fill) this happens to be correct. For partial/multi-fill rolls, it's not: two STO fills at different premiums produce the wrong net credit because prices are added, not averaged by contracts. Additionally, transaction fees are not subtracted from net credit anywhere.

## Proposed approach

1. **Add BTC branch to `aggregate_executions()`** — mirror the SELL_CC branch:
   ```python
   elif action == "BUY_TO_CLOSE":
       total_contracts = sum(int(e.get("contracts") or 0) for e in executions)
       btc_cash = sum(
           float(e.get("execution_price") or 0) * int(e.get("contracts") or 0)
           for e in executions
       ) * 100  # per-share → per-contract × 100
       if total_contracts > 0:
           summary.weighted_avg_price = btc_cash / (total_contracts * 100)
           summary.execution_price    = summary.weighted_avg_price
       summary.total_contracts = int(total_contracts)
   ```

2. **Update ROLL branch to be contract-weighted** — instead of summing raw prices:
   ```python
   btc_cash = sum(float(e.get("execution_price") or 0) * int(e.get("contracts") or 0)
                  for e in btc_legs) * 100
   sto_cash = sum(float(e.get("premium") or e.get("execution_price") or 0) * int(e.get("contracts") or 0)
                  for e in sto_legs) * 100
   total_contracts = max(
       sum(int(e.get("contracts") or 0) for e in btc_legs),
       sum(int(e.get("contracts") or 0) for e in sto_legs),
       1,
   )
   total_fees = sum(float(e.get("fees") or 0) for e in executions)
   net_cash = sto_cash - btc_cash - total_fees
   summary.execution_price = net_cash / (total_contracts * 100)  # per-share net credit
   ```

3. **Update `_resolve_chain()` to use `aggregate_executions()` for terminal BTC** — once BTC aggregation is fixed, replace the raw-fill loop with:
   ```python
   btc_summary = agent_db.aggregate_executions(raw_execs, "BUY_TO_CLOSE")
   if btc_summary and btc_summary.get("execution_price"):
       terminal_btc = float(btc_summary["execution_price"])
       extra = accumulated_extra - terminal_btc
   ```

4. **For intermediate ROLL hops** — `exec_rec` is already from `get_completed_chain_child()` which calls `aggregate_executions()` for ROLL actions. This will be automatically improved by fix #2.

## Touches

- `agent_db.py` — `aggregate_executions()`: BTC branch + contract-weighted ROLL branch + fee deduction
- `agents/outcome_evaluator.py` — `_resolve_chain()` terminal BTC: use aggregated exec_rec instead of raw fill loop
- `tests/test_cc_management.py` / `tests/test_lifecycle.py` — test multi-fill BTC and multi-fill ROLL weighted correctly

## Done when

- [ ] `aggregate_executions("BUY_TO_CLOSE", ...)` returns `execution_price` = contract-weighted avg per share
- [ ] `aggregate_executions("ROLL_*", ...)` returns `execution_price` = contract-weighted net credit per share, net of fees
- [ ] `_resolve_chain()` uses `aggregate_executions()` for terminal BTC instead of raw fill loop
- [ ] Test: 1 contract @ $2 + 3 contracts @ $4 BTC → `execution_price = 3.50` (not 3.00)
- [ ] Test: ROLL with fees → net credit reduced by fee per share
- [ ] All existing tests pass
