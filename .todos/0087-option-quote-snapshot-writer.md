# Option Quote Snapshot Writer

- **ID:** 0087
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** 0086

## Problem

`agent_db.py` has `upsert_option_quote_snapshot()` and an `option_quote_snapshots` table, but nothing calls them. `covered_call_rec.py` and `agents/covered_call_agent.py` evaluate option chains and choose contracts but never persist IV, bid/ask, or spread to the database. So `_check_option_iv()` and `_check_option_liquidity()` in `dependency_checker.py` always return no data — the dependency infrastructure exists but produces no signal.

## Proposed approach

- In `covered_call_rec.py`, after evaluating a contract chain and selecting the best contract, call `agent_db.upsert_option_quote_snapshot()` for:
  - The selected contract
  - Top 3 alternatives considered
  - Any currently open CC contracts for the ticker (if chain data is available)
- Store: ticker, strike, expiration, iv, bid, ask, spread_pct (= (ask-bid)/ask), captured_at
- Do not store every contract in the chain indefinitely — limit to the above set to avoid SQLite bloat.
- In `agents/covered_call_agent.py`, wire the same upsert after the agent evaluates contracts via LLM.
- Snapshots should be upserted (not appended) per (ticker, strike, expiration) + date, so re-runs don't create duplicate rows.

## Touches

- `covered_call_rec.py` — upsert after contract selection
- `agents/covered_call_agent.py` — upsert after LLM evaluation
- `agent_db.py` — verify `upsert_option_quote_snapshot()` handles the selected+alternatives pattern cleanly
- `tests/` — test that CC evaluation path persists at least one snapshot row

## Done when

- [ ] Running CC analysis for a ticker with a live chain creates rows in `option_quote_snapshots`
- [ ] Selected contract + top 3 alternatives are persisted
- [ ] `get_latest_option_snapshot(ticker, strike, expiration)` returns a non-None row after CC runs
- [ ] `_check_option_iv()` can now detect IV change using stored snapshot
