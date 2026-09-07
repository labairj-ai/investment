# Fix Tax Agent NO ACTION State Hash to Use Real Tax Infrastructure

- **ID:** 0108
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

`_compute_no_action_state_extras()` in `orchestrator.py` derives the Tax Agent's NO ACTION hash from `executed_actions`, which is wrong in two ways. First, `lt_lots_count` counts `executed_actions` rows whose `execution_date` crossed the one-year mark — but `executed_actions` only tracks trades logged through the system, not all open tax lots. Second, `realized_gain_bucket` computes `execution_price - e.get("avg_cost", 0)` per row, but `executed_actions` has no `avg_cost` column, so `e.get("avg_cost", 0)` always returns 0, making every sale appear to realize the full sale price as a gain. A $150 sale on a $140 basis position looks like a $150 gain rather than $10.

## Proposed approach

- For `lt_lots_count`: query `cost_lots` for lots held more than 365 days as of today (using `purchase_date`); count rows where `(today - purchase_date).days >= 365`. This is the canonical list of open long-term lots.
- For `realized_gain_bucket`: query `sell_transactions` (or equivalent — whichever table records realized sales with basis) for YTD rows; sum `(sale_price - basis_price) * quantity`; bucket to nearest $500. If no such table exists, fall back to `executed_actions` but only for actions where the system has a reliable cost basis available (e.g. look up `avg_cost` from `cost_lots` by ticker before computing gain).
- Add `get_lt_lots_count()` and `get_ytd_realized_gain()` helpers to `agent_db.py` so the orchestrator does not contain raw SQL.
- Add unit tests for both helpers using an in-memory DB seeded with `cost_lots` rows.

## Touches

- `agents/orchestrator.py` — `_compute_no_action_state_extras()` Tax branch
- `agent_db.py` — `get_lt_lots_count()`, `get_ytd_realized_gain()` helpers
- `tests/test_agent_db.py` — unit tests for new helpers
- `tests/test_lifecycle.py` — lifecycle test that seeds `cost_lots` and verifies Tax hash changes when a lot crosses the LT threshold

## Done when

- [ ] `get_lt_lots_count()` queries `cost_lots`, not `executed_actions`; returns correct count for seeded test data with a mix of short-term and long-term lots.
- [ ] `get_ytd_realized_gain()` returns a value that reflects actual basis (not zero); verified with a test where basis ≠ 0.
- [ ] `_compute_no_action_state_extras()` Tax branch calls the new helpers; no direct SQL against `executed_actions` for tax-state derivation remains.
- [ ] Lifecycle test: seed one LT lot in `cost_lots`; confirm Tax hash changes vs. a snapshot with zero LT lots.
- [ ] Lifecycle test: seed a YTD sale with known gain; confirm `realized_gain_bucket` reflects actual gain (not full sale price).
- [ ] Full pytest suite passes.
- [ ] On optiplex: run the orchestrator dry-run and inspect the Tax agent NO ACTION hash extras in `agent_runs.input_snapshot_json`; confirm `lt_lots_count` matches the count of holdings held > 1 year.
