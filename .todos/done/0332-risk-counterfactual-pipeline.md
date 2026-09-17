# Build Risk Counterfactual Pipeline: Capture + Label Rejected Trades

- **ID:** 0332
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0331

## Problem

The `risk_counterfactual_outcomes` table exists and the Risk Gate Audit card in Learning Lab reads from it, but no writer exists anywhere in the risk or execution paths. The table is permanently empty. The Risk Gate Audit card therefore cannot answer whether individual risk rules prevented losses or blocked profitable trades.

To make the question answerable, every risk rejection needs to be captured with enough detail (failed rule, proposed trade parameters) that the outcome labeler can later compute what would have happened if the trade had been allowed through.

## Proposed approach

**Risk engine — capture rejections:**
- When a `TradeIntent` is rejected by the risk engine, write a row to `risk_counterfactual_outcomes` containing: `trade_intent_id`, `episode_id` (via the now-wired lineage from 0331), `rejected_at` timestamp, `failed_rule` (the specific rule name/ID that caused rejection), `proposed_ticker`, `proposed_action`, `proposed_quantity`, `proposed_notional`, and `decision_date` (market date in America/New_York).
- A single intent can fail multiple rules; record the first (most-restrictive) or all rules that fired, with a `rejection_reason` text field for human readability.

**Outcome labeler — evaluate blocked trades:**
- Extend `daily_outcome_labeler.py` (from 0328) to scan `risk_counterfactual_outcomes` rows that do not yet have outcome data.
- For each unresolved counterfactual, compute return at 1w, 1m, and 3m horizons from `decision_date`, using the same price-fetch logic as the episode outcome labeler.
- Write results back to `risk_counterfactual_outcomes`: `return_1w`, `return_1m`, `return_3m`, `spy_return_1w`, `spy_return_1m`, `spy_return_3m`, `alpha_1w`, `alpha_1m`, `alpha_3m`.
- Mark label completeness with `labeled_at` timestamp per horizon.

**Risk Gate Audit card in Learning Lab:**
- Once data flows, the card should show: rule name, rejection count, average counterfactual alpha vs SPY at 1m/3m, fraction of rejections that would have been profitable.
- No UI work required here — the card already queries the table. Just verify it renders correctly once rows exist.

**decision_date timezone:**
- Use America/New_York + exchange calendar for all `decision_date` derivation (addresses the UTC issue called out in 0333; apply the same fix here consistently).

## Touches

- `trade_engine/risk_engine.py` — write `risk_counterfactual_outcomes` row on rejection
- `db/migrations/` — audit `risk_counterfactual_outcomes` schema; add any missing columns (`failed_rule`, `rejection_reason`, `episode_id`, `decision_date`, outcome columns)
- `scripts/daily_outcome_labeler.py` (or equivalent) — extend to label counterfactual rows
- `agent_db.py` — helpers to insert counterfactual row and update with labeled outcomes
- `tests/` — assert that a rejected intent produces a counterfactual row; assert labeler populates outcome fields

## Done when

- [x] Every `TradeIntent` rejection by the risk engine writes a row to `risk_counterfactual_outcomes` with `failed_rule`, `episode_id`, `proposed_*` fields, and `decision_date` in ET market-calendar terms
- [x] `daily_outcome_labeler.py` labels unresolved counterfactual rows at 1w/1m/3m with SPY-relative alpha
- [x] Risk Gate Audit card in Learning Lab renders non-empty results (at least 1w horizon) after one labeler run
- [x] `python -m pytest tests/` passes with no regressions

## Outcome

4 files changed. `agent_db.py`: extended `risk_counterfactual_outcomes` schema with `episode_id`, `rejection_reason`, `decision_date`, `mfe`, `mae` columns (in both CREATE TABLE and `_new_cols` migrations). `trade_engine/risk_engine.py`: `_finalize()` calls `_write_counterfactual_rejection()` on REJECTED decisions; new function looks up symbol/side/qty/limit_price/episode_id from `trade_intents`, finds first FAIL check for rule/reason, computes ET decision_date, INSERTs base row with `horizon=NULL`. Bug found and fixed: column is `symbol` not `ticker` in trade_intents. `agents/learning/outcome_labeler.py`: `label_risk_counterfactuals()` scans base rows (horizon IS NULL), applies 1w/1m/3m horizons, computes ticker/SPY returns + alpha + MFE/MAE, inserts labeled rows with `INSERT OR IGNORE`. `tests/test_outcome_labeler.py`: 3 new tests in `TestRiskCounterfactualPipeline` covering labeler write, idempotency, and risk engine rejection capture. 763 passed, 16 skipped.
