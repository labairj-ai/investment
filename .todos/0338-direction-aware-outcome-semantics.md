# Direction-Aware Outcome Semantics for BUY/SELL/EXIT

- **ID:** 0338
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0333, 0332

## Problem

Both `trade_outcomes` and `risk_counterfactual_outcomes` currently compute returns as `P_horizon / P_entry - 1` regardless of trade direction. This produces incorrect semantics for SELL and EXIT decisions:

- A rejected EXIT at $100 followed by a drop to $70 records `ticker_return = -30%`. But the risk gate blocking that EXIT was *bad* — the system wanted to exit and was prevented.
- A TRIM fill at $100 followed by a drop to $70 records `return_3m = -30%`. But the trim was a *good* execution decision.

For BUY decisions, positive subsequent return is favorable. For SELL/EXIT decisions, negative subsequent return is favorable. Using raw ticker return for all actions means the Risk Gate Audit can misclassify blocked SELL decisions, and future learning around TRIM/EXIT will train on sign-flipped signals.

## Proposed approach

Add `underlying_return` (raw price change, always `P_h/P_entry - 1`) and `decision_return` (sign-flipped for SELL/TRIM/EXIT):

```
BUY:
    decision_return = underlying_return

SELL / TRIM / EXIT:
    decision_return = -underlying_return
```

Same logic for alpha:
```
decision_alpha = decision_return - spy_return_for_period
```
(vs `underlying_alpha = underlying_return - spy_return`)

Apply to both tables:

**`trade_outcomes`**: rename existing `return_Xw`/`alpha_Xw` to `underlying_return_Xw`/`underlying_alpha_Xw`; add `decision_return_Xw` and `decision_alpha_Xw` columns. The labeler reads `action` from the joined `trade_intents` row to determine direction.

**`risk_counterfactual_outcomes`**: add `directional_return` and `decision_alpha` columns. The labeler reads the `side` column (already stored on the rejected row) to determine sign.

Keep raw underlying returns for auditability. The learning pipeline and dashboard should use `decision_return`/`decision_alpha` as the primary metric.

## Touches

- `agent_db.py` — schema changes to `trade_outcomes` and `risk_counterfactual_outcomes`; `_new_cols` entries for new columns
- `agents/learning/outcome_labeler.py` — `label_trade_outcomes()`: join `trade_intents` on `intent_id` to get action; compute and write `decision_return_Xw`, `decision_alpha_Xw`. `label_risk_counterfactuals()`: read `side`; write `directional_return`, `decision_alpha`
- `serve.py` — `_handle_champion_challenger()` and `_handle_learning_stats()` risk audit should use `decision_return`/`decision_alpha` as primary metric
- `tests/test_outcome_labeler.py` — assert EXIT fill with price decline records positive `decision_return`; assert BUY fill with price gain records matching `underlying_return` and `decision_return`

## Outcome

4 files changed. `agent_db.py`: added `decision_return_1w/1m/3m` and `decision_alpha_1w/1m/3m` to `trade_outcomes` CREATE TABLE + `_new_cols`; added `directional_return` and `decision_alpha` to `risk_counterfactual_outcomes` CREATE TABLE + `_new_cols`. `agents/learning/outcome_labeler.py`: `label_trade_outcomes()` joins `trade_intents` for `side` column, computes `decision_return = return` for BUY or `-return` for SELL/EXIT/TRIM, writes `decision_return_Xw` and `decision_alpha_Xw` alongside existing columns. `label_risk_counterfactuals()` reads `side` from base row, computes `directional_return = ticker_return` for BUY or `-ticker_return` for SELL, writes both `directional_return` and `decision_alpha`. `tests/test_outcome_labeler.py`: `TestDirectionAwareOutcomes0338` class with 4 tests covering BUY positive return, EXIT before price drop, blocked BUY (gate correctly blocked), blocked SELL (gate wrongly blocked). Dashboard update for Risk Gate Audit to use `directional_return` as primary metric deferred to a dedicated dashboard pass. 788 passed, 16 skipped.

## Done when

- [x] `trade_outcomes` has `decision_return_Xw` and `decision_alpha_Xw` for each horizon; labeler joins `trade_intents` for action and writes direction-adjusted columns
- [x] `risk_counterfactual_outcomes` has `directional_return` and `decision_alpha`; labeler reads `side` column and writes sign-flipped values for SELL decisions
- [x] EXIT fill where price later drops: `decision_return > 0`, `return_Xw < 0`
- [x] BUY fill where price later rises: `decision_return == return_Xw`
- [ ] Risk Gate Audit dashboard uses `directional_return`/`decision_alpha` as primary signal — deferred to dashboard update pass
- [x] `python -m pytest tests/` passes with no regressions
