# Causal Portfolio Themes

- **ID:** 0593
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0589

## Problem

`detect_portfolio_themes()` groups events by `(event_type, direction)` across tickers and fires a theme alert when 3+ holdings share the combination. Three unrelated EARNINGS disappointments — one from a retailer missing consumer demand, one from a semiconductor on supply constraints, one from a bank on credit costs — all share `(EARNINGS, NEGATIVE)` and generate a spurious "portfolio theme". The theme label would say "EARNINGS NEGATIVE across AAPL, JPM, TGT" which tells the user nothing about why these are correlated or whether they are correlated at all.

## Proposed approach

- Add a `causal_driver` field to each extracted event using a controlled vocabulary: `AI_CAPEX`, `USD_STRENGTH`, `RATES_HIGHER`, `CONSUMER_WEAKNESS`, `CHINA_DEMAND`, `FREIGHT_WEAKNESS`, `ENERGY_INPUT_COST`, `TARIFFS`, `SUPPLY_CONSTRAINT`, `CREDIT_TIGHTENING`, `REGULATORY_PRESSURE`, `OTHER`. The LLM populates it optionally; `OTHER` is the default if the LLM does not identify a macro/cross-sector driver.
- Theme detection groups by `(causal_driver, direction)` where `causal_driver != OTHER` and 3+ distinct holdings share it. Generic `event_type` grouping is removed as a standalone theme trigger.
- Add `causal_driver TEXT` column to `news_events` table.
- Update extraction prompt to request `causal_driver` from the vocabulary.

## Touches

- `agents/news/intelligence.py` — `extract_events_llm()` prompt, `detect_portfolio_themes()` grouping logic
- DB schema — `news_events` table: add `causal_driver TEXT` column

## Done when

- [ ] LLM extraction prompt includes `causal_driver` field with controlled vocabulary
- [ ] `causal_driver` is persisted in `news_events`
- [ ] Theme detection groups by `(causal_driver, direction)` not `(event_type, direction)`
- [ ] Events with `causal_driver = OTHER` do not generate portfolio themes
- [ ] Three unrelated EARNINGS events with different causal drivers do NOT fire a theme alert
- [ ] Three tickers with `causal_driver = USD_STRENGTH` and same direction DO fire a theme alert
