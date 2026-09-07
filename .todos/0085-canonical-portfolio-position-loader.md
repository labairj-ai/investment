# Canonical Portfolio Position Loader

- **ID:** 0085
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

`generate_dashboard.py:load_csv_holdings()` iterates every CSV row and does `result[ticker] = {...}`, meaning the last row wins when holdings.csv contains multiple lots for the same ticker. `agents/snapshot.py` already aggregates correctly using weighted-average cost across lots. This creates a silent inconsistency: the dashboard may show ANET as 70 shares @ $145 while the agent snapshot sees 120 shares at a blended $129. Users comparing agent output to the dashboard see mismatched weights and share counts.

## Proposed approach

- Create `portfolio_positions.py` at the project root with:
  - `load_positions() → dict[str, Position]` — aggregated (weighted-avg cost, total shares) per ticker
  - `get_position(ticker) → Position | None`
  - `get_lots(ticker) → list[Lot]` — all individual CSV rows for a ticker
  - `Position` and `Lot` as simple dataclasses or TypedDicts
- Wire `generate_dashboard.py` to use `portfolio_positions.load_positions()` instead of `load_csv_holdings()`.
- Wire `covered_call_rec.py` to use it instead of its own CSV reader.
- Check `send_newsletter_main.py` and `tax_agent.py` for any other direct CSV readers and migrate them.
- `agents/snapshot.py` can remain the canonical path for the agent pipeline but should import from `portfolio_positions.py` to avoid duplicating the aggregation logic.

## Touches

- `portfolio_positions.py` (new)
- `generate_dashboard.py` — replace `load_csv_holdings()` call
- `covered_call_rec.py` — replace direct CSV reading
- `agents/snapshot.py` — import shared aggregation or verify equivalence
- `send_newsletter_main.py`, `tax_agent.py` — audit for independent CSV readers
- `tests/` — add test for multi-lot aggregation via `portfolio_positions`

## Done when

- [ ] `portfolio_positions.py` exists with `load_positions()`, `get_position()`, `get_lots()`
- [ ] `generate_dashboard.py` uses it; multi-lot tickers show correct blended shares + cost
- [ ] `covered_call_rec.py` uses it
- [ ] No other file in the project does its own raw CSV loop over holdings.csv
- [ ] Test: CSV with 2 lots for same ticker → `load_positions()` returns single aggregated entry
