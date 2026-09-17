# Real Execution Benchmarking

- **ID:** 0350
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** low
- **Depends:** 0339

## Problem

`trade_outcomes.arrival_price` is currently populated from `trade_intents.limit_price` at fill-spawn time. That conflates two distinct prices that tell opposite stories about execution quality:

- **Decision/arrival price** = market price available when the recommendation was created (the price at which you *decided* to trade)
- **Limit price** = maximum (BUY) or minimum (SELL) price you're willing to accept
- **Fill price** = actual execution price

Example: market at decision = $100, limit = $101, fill = $100.80
- Fill vs limit: −$0.20 favorable (you beat your limit)
- Implementation shortfall vs decision: +$0.80 adverse (you paid $0.80 more than the pre-decision market)

These tell opposite-looking stories. Reporting only fill-vs-limit as "implementation shortfall" is mislabeled and misleading. Until bid/ask/mid is captured at decision time, the implementation shortfall metric reports fill-vs-limit variance, not true IS.

## Proposed approach

**Capture at recommendation/intent creation time:**
- `recommendations.decision_bid REAL` — bid at time of recommendation
- `recommendations.decision_ask REAL` — ask at time of recommendation
- `recommendations.decision_mid REAL` — mid = (bid+ask)/2 at time of recommendation

Or alternatively on `trade_intents`:
- `trade_intents.decision_market_price REAL` — last/mid price at intent creation
- `trade_intents.decision_bid REAL`
- `trade_intents.decision_ask REAL`

**Two separate execution metrics in `trade_outcomes`:**
- `implementation_shortfall REAL` — fill vs decision_mid: `(P_fill − P_decision) / P_decision` for BUY, sign-flipped for SELL; measures true decision-to-fill cost
- `limit_variance REAL` — fill vs limit_price: `(P_fill − P_limit) / P_limit` for BUY; measures whether limit was tight or loose

**Quote source:** use Alpaca's `get_latest_trade()` or `get_snapshot()` at intent-creation time; fall back to the DB price cache (buffett_winners.price or yfinance) if Alpaca quote is unavailable. Store the source in a `price_source TEXT` column.

**Reporting:**
- `/api/learning/champion-challenger` `execution_quality` block: report mean IS, mean limit_variance, and mean spread cost per action type
- Display in dashboard alongside the existing implementation_shortfall stat

Alpaca commissions are currently zero, so fee effects are negligible — but the IS and limit_variance metrics will matter more as execution is tuned.

## Touches

- `agent_db.py` — `decision_market_price`, `decision_bid`, `decision_ask` on `trade_intents` in CREATE TABLE + `_new_cols`; `limit_variance` on `trade_outcomes` + `_new_cols`
- `trade_engine/models.py` — `TradeIntent` gains the three decision-price fields
- `trade_engine/intent_builder.py` — attempt live quote fetch at intent creation time to populate decision prices; fall back gracefully
- `trade_engine/execution_engine.py` — `_spawn_trade_outcome()`: write `limit_variance` from fill vs `ti.limit_price`; `implementation_shortfall` from fill vs `ti.decision_market_price` (not limit_price)
- `agents/learning/outcome_labeler.py` — `label_trade_outcomes()`: use `decision_market_price` for IS calculation when available; note the semantic change vs current (fill-vs-limit)
- `serve.py` — expose `limit_variance` in execution_quality block
- `tests/` — assert IS = fill vs decision_market_price (not limit); assert limit_variance = fill vs limit_price; assert fallback to NULL when no decision price available

## Done when

- [ ] `trade_intents` stores `decision_market_price` (bid/ask/mid) at intent creation time
- [ ] `implementation_shortfall` = fill vs decision_market_price (not limit price)
- [ ] `limit_variance` = fill vs limit_price stored separately in `trade_outcomes`
- [ ] Both metrics visible in the champion-challenger execution quality API block
- [ ] Tests distinguish IS from limit_variance semantically
- [ ] `python -m pytest tests/` passes with no regressions
