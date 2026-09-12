# Dashboard Portfolio Weight: Fully Live Denominator

- **ID:** 0186
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** none

## Problem

0184 improved the weight numerator to `cost_lots shares × effective_price` (live). But the denominator is still `portfolio_day.total_value` — an end-of-day snapshot written once per day.

Example: if ANET rises 20% intraday, the denominator stays at yesterday's total. The `only_if_overweight` gate then computes:
```
weight = (shares × $120) / $100,000  ←  correct numerator
                         ^^^^^^^^^^^
                    yesterday's total (wrong denominator)
```
True weight is `$12,000 / $102,000 = 11.76%`, but the dashboard computes `12,000 / 100,000 = 12.0%`. While close here, a move in a highly concentrated position can shift the denominator materially enough to flip the gate.

The agent uses the canonical snapshot from `AgentContext.snapshot` (which loads `holdings.csv` via `load_positions()` with intraday prices), so agent and dashboard can still diverge on `only_if_overweight`.

## Proposed approach

In `_build_mgmt_context_from_db()`, after computing `live_value = total_shares × effective_price` for this ticker, also compute the total portfolio value from `cost_lots` using the latest price for each ticker:

1. Query all tickers in `cost_lots`: `SELECT DISTINCT ticker FROM cost_lots`
2. For each ticker, get total shares: `SELECT SUM(shares) FROM cost_lots WHERE ticker=?`
3. For each ticker, get the latest price from `holding_day` (best available without a live fetch for other tickers): `SELECT price FROM holding_day WHERE ticker=? ORDER BY day DESC LIMIT 1`
4. Total portfolio value = `sum(shares × price for each ticker)`
5. For this ticker specifically, substitute `effective_price` (live) instead of the stale `holding_day` price

This gives a denominator that is live for the current ticker and EOD for others — a meaningful improvement without requiring a live data fetch for all holdings. It's much better than all-EOD and removes the current ticker's contribution to the denominator error.

The fully-clean fix (agent parity) would be to call `load_positions()` and pass live prices for all tickers into `_build_mgmt_context_from_db()`, but that requires serve.py to compute the full portfolio snapshot before calling into the management context builder. That refactor can be a separate step.

## Touches

- `covered_call_rec.py` — `_build_mgmt_context_from_db()` portfolio weight block (~line 1121)
- `tests/test_cc_management.py` — extend 0184 test to verify live denominator (current ticker's price used in both numerator and denominator; other tickers use EOD)

## Done when

- [ ] Portfolio denominator is rebuilt from `cost_lots` shares × latest price (EOD for other tickers, live for current)
- [ ] Current ticker's intraday move affects both numerator and denominator consistently
- [ ] Falls back to `portfolio_day.total_value` when `cost_lots` is absent or empty
- [ ] Test: ANET up 20% → weight uses $12,000 / $102,000 (approx), not $12,000 / $100,000
- [ ] All existing tests pass
