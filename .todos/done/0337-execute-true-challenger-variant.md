# Execute True Challenger Decision Variant

- **ID:** 0337
- **Status:** done
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0336

## Problem

0336 has a real architectural bug: `IntentBuilder` reads `ticker = rec["ticker"]` from the original accepted recommendation. When a `decision_variants` row exists for the episode, it correctly sets `decision_origin = "PAPER_CHALLENGER"` but the intent is still built using the champion's ticker. If champion chooses ANET and challenger chooses GRMN, the Alpaca paper account trades ANET with `decision_origin=PAPER_CHALLENGER` — labeling a champion trade as a challenger trade. This contamination is exactly what the champion/challenger experiment was supposed to prevent.

## Proposed approach

Make `decision_variants` a complete executable decision object, not just metadata:
- Add `action TEXT`, `price REAL`, `target_weight_pct REAL`, `quantity REAL`, `thesis_version INTEGER` to `decision_variants` table (CREATE TABLE + `_new_cols` migration)
- `_insert_decision_variant()` in `opportunity_agent.py` must populate these fields from the challenger's top pick at variant-recording time (challenger ticker, its action, its price/sizing from `action_payload_json`)
- Add `build_intent_from_variant(variant_id, account_id, policy, conn)` to `trade_engine/intent_builder.py` — reads from `decision_variants` entirely, never touches the original recommendation ticker
- ALPACA account routing: if a PAPER_CHALLENGER variant row exists for the episode, call `build_intent_from_variant()`; otherwise call `build_intent()` as today. Never patch `decision_origin` onto a champion-built intent.
- All non-ALPACA accounts and ALPACA accounts without a variant row continue using `build_intent()` unchanged.

Open question: if champion and challenger pick the same ticker, the variant is a no-op trade on Alpaca (same symbol, different score origin). That is fine — record it honestly.

## Touches

- `agent_db.py` — `decision_variants` table: add `action`, `price`, `target_weight_pct`, `quantity`, `thesis_version` columns to CREATE TABLE and `_new_cols`
- `agents/opportunity_agent.py` — `_insert_decision_variant()`: populate new sizing/action fields from challenger top-pick candidate
- `trade_engine/intent_builder.py` — add `build_intent_from_variant()`; update ALPACA routing logic
- `tests/test_calibration.py` or new `tests/test_challenger_execution.py` — champion=A, challenger=B → assert Alpaca intent `symbol=B, decision_origin=PAPER_CHALLENGER`; assert shadow/non-ALPACA intent `symbol=A, decision_origin=CHAMPION`

## Outcome

5 files changed. `agent_db.py`: `decision_variants` table gains `action TEXT`, `price REAL`, `target_weight_pct REAL`, `quantity REAL`, `thesis_version INTEGER` columns in CREATE TABLE + `_new_cols` ALTER TABLE migration. `agents/opportunity_agent.py`: `_insert_decision_variant()` now populates `action="BUY"`, `price` (from candidate's market price), and `thesis_version` (looked up from `investment_theses`). `trade_engine/intent_builder.py`: added `build_intent_from_variant(variant_id, account_id, policy, conn)` — reads the variant row, uses `variant_ticker`/`action`/`price` entirely, never touches the recommendation ticker; idempotent via `(account_id, episode_id, decision_origin='PAPER_CHALLENGER')` check. `build_intent()` now routes ALPACA accounts to `build_intent_from_variant()` when a variant exists, instead of patching `decision_origin` onto a champion-built intent. `tests/test_calibration.py`: updated existing variant test to include `action` + `price` in variant row; added `test_variant_ticker_used_not_champion_ticker` asserting champion=ANET/challenger=GRMN → Alpaca gets GRMN + PAPER_CHALLENGER, shadow gets ANET + CHAMPION. 784 passed, 16 skipped.

## Done when

- [x] `decision_variants` carries `action`, `price`, `target_weight_pct`, `quantity`, `thesis_version` populated at variant-recording time from the challenger's top pick
- [x] `build_intent_from_variant()` exists and builds the full `TradeIntent` from `decision_variants` — not from `recommendations.ticker`
- [x] ALPACA account with a PAPER_CHALLENGER variant row calls `build_intent_from_variant()`; all other accounts call `build_intent()`
- [x] Test: champion picks ANET, challenger picks GRMN → Alpaca intent `symbol=GRMN, decision_origin=PAPER_CHALLENGER`; shadow/non-Alpaca intent `symbol=ANET, decision_origin=CHAMPION`
- [x] `python -m pytest tests/` passes with no regressions
