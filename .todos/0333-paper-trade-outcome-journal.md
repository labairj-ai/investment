# Paper Trade Outcome Journal: Execution-Aware Trade Returns

- **ID:** 0333
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0331

## Problem

The current outcome labeler (0328) measures return from the market close on the decision date. That produces a useful counterfactual signal — "was this a good stock idea?" — but it is not a paper-trade performance measurement. A good idea at a bad fill price is a poor trade. Conversely, a mediocre idea can succeed through excellent execution.

Fill objects already carry the data needed: actual fill price, quantity, fees, cost basis, and realized P&L. That information is currently unused by the learning system. Until trade-level outcomes exist as a separate label, the system cannot distinguish "stock selection quality" from "execution quality," and the challenger model will be trained on a signal that does not reflect actual trading performance.

Two semantically distinct outcome labels are needed:

| Label type | Entry price | Includes fees |
|------------|-------------|---------------|
| `COUNTERFACTUAL_SIGNAL_RETURN` | Market close on decision date | No |
| `EXECUTED_TRADE_RETURN` | Actual Alpaca fill price + fees | Yes |

## Proposed approach

**New table: `trade_outcomes`**
- `id`, `fill_id` (FK to `fills`), `episode_id` (FK to `decision_episodes`), `trade_intent_id`
- `ticker`, `action`, `decision_date` (ET market-calendar date), `fill_date`
- Entry: `fill_price`, `fill_quantity`, `fill_fees`, `cost_basis_per_share`
- Realized: `realized_pnl`, `realized_return_pct`
- Unrealized marks at horizons: `mark_1w`, `mark_1m`, `mark_3m` (last close before/on horizon date)
- `return_1w`, `return_1m`, `return_3m` — computed from fill price + fees as entry
- `spy_return_1w`, `spy_return_1m`, `spy_return_3m` — SPY benchmark from same fill date
- `alpha_1w`, `alpha_1m`, `alpha_3m`
- `mae_pct`, `mfe_pct` — max adverse / max favorable excursion from fill price (requires daily marks)
- `label_type` — `EXECUTED_TRADE_RETURN` (vs the episode-level `COUNTERFACTUAL_SIGNAL_RETURN`)
- `labeled_at` per horizon

**Outcome labeler extension:**
- After each fill ingestion, create a `trade_outcomes` row with fill price and date as entry.
- Daily labeler scans unlabeled `trade_outcomes` rows and computes 1w/1m/3m returns, MAE/MFE (using stored daily position marks from `position_snapshots` or `holding_day`).

**Timezone fix:**
- `_entry_date()` currently derives the date in UTC. A late-evening ET run becomes the next UTC date. Fix `_entry_date()` and any equivalent date derivation to use America/New_York + exchange calendar. Apply consistently in the episode labeler (0328) and counterfactual pipeline (0332) as well.

**Learning Lab — diagnostic horizon selector:**
- Add a 1w → 1m → 3m → 6m → 12m horizon toggle to Learning Lab now.
- Clearly mark 1w and 1m as "diagnostic only" — they mature sooner and let you validate that capture, price fetching, ticker returns, SPY returns, MFE/MAE, selected status, and missing-data rates are all working correctly before 3m labels exist.
- Do not train the main challenger from 1w/1m labels.

## Touches

- `db/migrations/` — new `trade_outcomes` table
- `agent_db.py` — insert/update helpers for `trade_outcomes`
- `scripts/daily_outcome_labeler.py` — extend to create and label `trade_outcomes` rows from fills
- `agents/learning/` — wherever challenger training reads labels, ensure it can specify which label type to train from
- `generate_dashboard.py` or `serve.py` — Learning Lab horizon selector UI
- `tests/` — assert that a fill produces a trade_outcomes row; assert MAE/MFE computed correctly; assert entry price differs from counterfactual signal entry

## Done when

- [ ] `trade_outcomes` table created with fill-price entry, fee-adjusted returns, MAE/MFE, and SPY alpha at 1w/1m/3m horizons
- [ ] Every Alpaca paper fill automatically spawns a `trade_outcomes` row at fill ingestion time
- [ ] Daily labeler populates return/alpha/MAE/MFE fields once horizon dates are reached
- [ ] `_entry_date()` (and all equivalent date derivations) uses America/New_York + exchange calendar, not UTC
- [ ] `COUNTERFACTUAL_SIGNAL_RETURN` and `EXECUTED_TRADE_RETURN` are distinguishable labels; challenger training can select by label type
- [ ] Learning Lab horizon selector (1w/1m/3m/6m/12m) present, with 1w/1m marked diagnostic-only
- [ ] `python -m pytest tests/` passes with no regressions
