# Capture Real Market Quote at Intent Creation Time

- **ID:** 0356
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0350

## Problem

`decision_market_price` is currently set to the pre-slippage recommendation price (the payload price from the opportunity agent), not a live market quote. `decision_bid` and `decision_ask` are in the schema but never populated. This means "implementation shortfall" is measured against a stale payload price rather than a true arrival-time market price, and there is no bid/ask capture to measure spread cost. Calling this "market price" is misleading when its provenance is a recommendation payload that may have been assembled hours before execution.

## Proposed approach

- In `build_intent_from_variant()` and `build_intent()` (the CHAMPION path), attempt to fetch a live quote from Alpaca at intent-creation time using `get_latest_trade()` or `get_snapshot()`
- Populate: `decision_last REAL`, `decision_bid REAL`, `decision_ask REAL`, `decision_mid REAL`, `decision_spread_bps REAL` (=(ask-bid)/mid × 10000), `quote_timestamp TEXT`
- Add these columns to `trade_intents` CREATE TABLE and `_new_cols`
- Store `decision_market_price = decision_mid` (or `decision_last` if mid unavailable); update intent_builder accordingly
- Fall back gracefully: if Alpaca quote unavailable, populate from DB price cache (yfinance buffett_winners.price), set a `price_source TEXT` column to `'alpaca_snapshot'` / `'db_cache'` / `'payload'`
- `_spawn_trade_outcome()`: use `decision_mid` (or `decision_last`) as the arrival price for IS; never use `limit_price` as an arrival price
- `serve.py` execution_quality block: add `mean_spread_bps` metric
- Add `price_source TEXT` and `quote_timestamp TEXT` to `trade_intents` schema + `_new_cols`

## Touches

- `trade_engine/intent_builder.py` — quote fetch at intent creation; populate all decision-price fields
- `agent_db.py` — `decision_last`, `decision_mid`, `decision_spread_bps`, `quote_timestamp`, `price_source` on `trade_intents` in CREATE TABLE + `_new_cols`
- `trade_engine/models.py` — `TradeIntent` dataclass gains new fields
- `trade_engine/execution_engine.py` — IS uses `decision_mid` not limit_price
- `serve.py` — expose `mean_spread_bps` in execution_quality
- `tests/` — test that quote fetch populates bid/ask; test IS uses mid not limit; test fallback to db_cache sets price_source correctly

## Done when

- [ ] `decision_bid`, `decision_ask`, `decision_mid`, `decision_spread_bps`, `quote_timestamp`, `price_source` populated at intent creation from a live Alpaca quote (or labeled fallback)
- [ ] `decision_market_price = decision_mid` (or `decision_last`) from an immutable quote snapshot
- [ ] IS in `trade_outcomes` computed against `decision_mid`, not `limit_price`
- [ ] `price_source` column records provenance: `alpaca_snapshot`, `db_cache`, or `payload`
- [ ] `python -m pytest tests/` passes with no regressions
