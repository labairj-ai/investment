# Define Symmetric Holding and Exit Policy for Virtual Books

- **ID:** 0357
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** normal
- **Depends:** 0351

## Problem

The virtual books (CHAMPION_BOOK, CHALLENGER_BOOK) receive BUY fills whenever the opportunity agent fires, but have no symmetric exit rule. Without an exit policy, books accumulate long positions until they either run out of cash or hit per-ticker limits, at which point they stop generating new comparative fills. This makes the long-run champion vs challenger NAV comparison meaningless: the books stop trading before enough comparative decisions accumulate. There is also the open question of how EXIT decisions from the live system interact with book simulation — should they be reflected in the books symmetrically?

## Proposed approach

- Define a holding period policy as a module constant: e.g., `BOOK_HOLD_DAYS = 63` (3 months, matching the alpha labeling horizon)
- After each BUY fill in a book, schedule a synthetic SELL at fill_date + BOOK_HOLD_DAYS; in practice, the nightly MTM job checks each open position's age and emits a SELL fill for positions older than HOLD_DAYS using the closing price on the exit date
- Alternatively: mirror EXIT/SELL decisions from the live opportunity agent into both books symmetrically (same action, same date, each book sells its own position)
- Ensure CHAMPION_BOOK exits the same ticker it bought (experiment_champion_ticker) and CHALLENGER_BOOK exits the ticker it bought (challenger_ticker) — they are independent books
- Update `record_virtual_fills()` to accept an optional holding-period exit trigger
- Update `compute_book_stats()` to reflect that positions do eventually close

**Open question:** should the exit date be fixed (fill + N days) or event-driven (next EXIT signal from opportunity agent for that ticker)? Fixed is simpler and more symmetric; event-driven more realistic. Recommend fixed first.

## Touches

- `agents/learning/book_simulator.py` — exit-policy logic; `BOOK_HOLD_DAYS` constant
- `agents/learning/book_mtm.py` (0351) — nightly job emits SELL fills for aged positions
- `agents/opportunity_agent.py` — optionally mirror EXIT decisions into both books
- `tests/test_book_simulator.py` — test that a position older than HOLD_DAYS produces a synthetic SELL fill on the next MTM run

## Done when

- [ ] A defined exit policy (fixed holding period or mirrored EXIT signals) prevents books from accumulating indefinite open positions
- [ ] Both books use the same exit rule (symmetric treatment)
- [ ] Positions older than the policy threshold are closed by the nightly MTM job
- [ ] `compute_book_stats()` reflects closed positions in turnover and return metrics
- [ ] `python -m pytest tests/` passes with no regressions
