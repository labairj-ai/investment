# Correct Decision/Episode Lineage Across Three Selections

- **ID:** 0358
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** high

## Problem

When the opportunity agent fires, up to three distinct tickers are selected:
- **LLM recommendation control** — the ticker the LLM chose (`champion_ticker`)
- **Experiment champion** — base-score top-1 (`experiment_champion_ticker`)
- **Challenger** — model-reranked top-1 (`variant_ticker`)

Each selection maps to a different candidate in `decision_episodes`, but the current code attaches a single `episode_id` to everything:

- `decision_variants.episode_id` is set from `champion.get("_episode_id")` — the LLM pick's episode — even though `variant_ticker` came from a different candidate.
- `book_simulator.record_virtual_fills()` receives `episode_id=selected.get("_episode_id")` where `selected` is the LLM winner — not the experiment champion or challenger.
- `build_intent_from_variant()` reads `var["episode_id"]` and stamps it onto the challenger trade intent.

Concrete example of the contamination:
```
LLM selected:        ANET  → episode_id = ep_anet
Experiment champion: GRMN  → episode_id = ep_grmn
Challenger:          SNA   → episode_id = ep_sna

decision_variants:
    variant_ticker = SNA
    episode_id     = ep_anet   ← WRONG

CHALLENGER_BOOK fill:
    ticker   = SNA
    episode_id = ep_anet       ← WRONG

When SNA's 90-day outcome is labeled, the feature row ep_anet
is treated as the training signal. ANET features predict SNA outcome.
```

This is quiet dataset contamination. It will silently produce wrong training signal once 90-day labels start maturing (≈December).

## Proposed approach

### Schema change — `decision_variants`

Add three explicit episode FK columns:

```sql
ALTER TABLE decision_variants ADD COLUMN recommendation_control_episode_id TEXT;
ALTER TABLE decision_variants ADD COLUMN experiment_champion_episode_id TEXT;
ALTER TABLE decision_variants ADD COLUMN challenger_episode_id TEXT;
```

Deprecate the existing `episode_id` FK on `decision_variants` (keep for backward compat, stop writing to it for new rows).

### Code changes — `opportunity_agent.py`

`_insert_decision_variant()` already receives `champion` (LLM pick) and `experiment_champion`. It also needs the challenger candidate. Pass all three `_episode_id` values and store them in the three new columns.

### Code changes — `book_simulator.py`

`record_virtual_fills()` signature becomes:
```python
def record_virtual_fills(
    champion_ticker: str,
    champion_episode_id: str,        # experiment_champion_episode_id
    challenger_ticker: str,
    challenger_episode_id: str,      # challenger_episode_id
    ...
)
```

### Code changes — `intent_builder.py`

`build_intent_from_variant()` reads `challenger_episode_id` from the variant row (falling back to `episode_id` for old rows) and stamps that onto the intent.

### Outcome labeler

When labeling episodes, the labeler should also update `decision_variants.variant_outcome_*` fields using `challenger_episode_id`, not the inherited `episode_id`.

## Touches

- `agent_db.py` — migration: add three episode ID columns to `decision_variants`
- `agents/opportunity_agent.py` — pass all three candidates' `_episode_id` values to `_insert_decision_variant()`
- `agents/learning/book_simulator.py` — `record_virtual_fills()` takes separate episode IDs per book
- `trade_engine/intent_builder.py` — read `challenger_episode_id` from variant row
- `agents/learning/outcome_labeler.py` — use `challenger_episode_id` for variant labeling
- `tests/test_calibration.py` — add test with three distinct tickers and assert all three episode IDs land in the correct columns
- `tests/test_book_simulator.py` — assert CHAMPION_BOOK fill uses experiment_champion_episode_id, CHALLENGER_BOOK fill uses challenger_episode_id

## Done when

- [ ] `decision_variants` has `recommendation_control_episode_id`, `experiment_champion_episode_id`, `challenger_episode_id` columns
- [ ] Each column is populated with the episode ID for its specific ticker, not the LLM-selected ticker's episode
- [ ] CHALLENGER_BOOK fill references `challenger_episode_id`; CHAMPION_BOOK fill references `experiment_champion_episode_id`
- [ ] Challenger trade intent carries `challenger_episode_id`
- [ ] Test with ANET/GRMN/SNA as separate tickers passes all three lineage assertions
- [ ] `python -m pytest tests/` passes with no regressions
