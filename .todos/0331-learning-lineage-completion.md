# Wire Learning Lineage: Episode → Recommendation → Intent → Fill

- **ID:** 0331
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** none

## Problem

The database schema anticipated the full learning lineage correctly — `episode_id` and `decision_origin` columns exist on `trade_intents`, and `recommendation_action` exists on `executed_actions` — but the plumbing is currently missing. The `TradeIntent` domain model does not expose `episode_id` or `decision_origin`. `IntentBuilder` does not populate them. `_write_executed_action()` writes the fill-side action (BUY/SELL) without populating `recommendation_action`. Additionally, `decision_episodes` does not yet record `base_score`, `challenger_score`, or `challenger_model_version`, so it is impossible to trace which model version influenced a specific ranking.

The result: you cannot unambiguously connect a paper fill back to the episode that originated it, the risk decision that permitted it, or the challenger model version that may have influenced it.

## Proposed approach

**TradeIntent domain model:**
- Add `episode_id: int | None` and `decision_origin: str | None` fields to the `TradeIntent` dataclass / model.
- Ensure all DB insert/read paths round-trip these fields.

**IntentBuilder:**
- When promoting a recommendation to a `TradeIntent`, look up the originating `decision_episode` via `recommendation_id` and populate `episode_id` and `decision_origin` on the intent row.

**_write_executed_action():**
- Populate `recommendation_action` with the action from the source recommendation (e.g. BUY, SELL_TRIM) rather than the fill-side action (BUY/SELL). The fill-side action can be derived; the original recommendation action is the semantically important label.

**decision_episodes — add three columns:**
- `base_score REAL` — the composite score produced by the formula before any challenger adjustment.
- `challenger_score REAL` — the score after applying the bounded adjustment (NULL if no model was active).
- `challenger_model_version TEXT` — the `model_version` string from the `learning_models` row used (NULL if none).
- These must be written at episode-capture time in `mark_episode_selected()` / the opportunity-agent path.

**Lineage target:**
```
decision_episode
  ├── base_score, challenger_score, challenger_model_version
  ↓
recommendation
  ↓
trade_intent
  ├── episode_id
  ├── decision_origin
  ↓
risk_decision
  ↓
order
  ↓
fill (recommendation_action populated)
```

## Touches

- `trade_engine/models.py` (or equivalent TradeIntent dataclass) — add `episode_id`, `decision_origin` fields
- `trade_engine/intent_builder.py` — populate `episode_id`, `decision_origin` when building intent
- `agent_db.py` or `trade_engine/db.py` — `_write_executed_action()` populate `recommendation_action`
- `db/migrations/` — migration adding `base_score`, `challenger_score`, `challenger_model_version` to `decision_episodes`
- `agents/opportunity_agent.py` — write base_score + challenger_score + model_version at episode capture time
- `agents/learning/challenger.py` — expose model_version on result so opportunity_agent can record it
- `tests/` — assert round-trip of episode_id on intent; assert recommendation_action is set on executed action

## Done when

- [ ] `TradeIntent` dataclass exposes `episode_id` and `decision_origin`; DB insert/read round-trips both fields
- [ ] `IntentBuilder` sets `episode_id` (from originating episode) and `decision_origin` on every new intent
- [ ] `_write_executed_action()` populates `recommendation_action` with the source recommendation's action, not the fill-side verb
- [ ] `decision_episodes` has `base_score`, `challenger_score`, `challenger_model_version` columns (migration); opportunity agent writes all three at capture time
- [ ] A single paper fill can be traced unambiguously: episode → recommendation → intent → risk_decision → order → fill (SQL join chain works end-to-end)
- [ ] `python -m pytest tests/` passes with no regressions
