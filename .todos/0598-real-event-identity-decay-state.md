# Real Event Identity and Decay State Machine

- **ID:** 0598
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0597

## Problem

Three bugs: (a) `event_fingerprint = hash(ticker+event_type+direction+affected_metric)` collapses different events sharing those fields (e.g. two separate GUIDANCE_CHANGE/POSITIVE/revenue events six months apart) and splits the same event when `affected_metric` wording varies ("revenue guidance" vs "FY27 revenue outlook"). This makes `CONFIRMING` and `ACCELERATING` unreliable. (b) `sweep_fading_resolved()` only selects combos with `n30 > 0`, making `RESOLVED` unreachable — every row in the loop necessarily gets `FADING`. (c) Synthetic `FADING`/`RESOLVED` markers are inserted back into `news_events` as if they were real observations. `compute_trend()` does not exclude them, so tomorrow's trend counts are inflated by synthetic state, which can self-perpetuate.

## Proposed approach

- Introduce `causal_event_key`: an LLM-supplied opaque string (e.g. `META_FY27_AI_NETWORK_CAPEX_RAISE`) that represents the identity of the underlying business event. This is distinct from `causal_driver` (macro category for cross-holding themes). Occurrence history in `compute_trend()` counts distinct `causal_event_key` values, not fingerprint values.
- Move `FADING`/`RESOLVED` state entirely out of `news_events` into a new `news_event_state` table: `(ticker, causal_event_key, last_real_seen_at, state TEXT, state_as_of TEXT)`.
- Rename `sweep_fading_resolved()` to `update_event_state_sweep()`. It reads `news_event_state` and `news_events` but never inserts into `news_events`. State transitions: real event today → `ACTIVE`; absent N days from last real observation → `FADING`; absent threshold days → `RESOLVED`.
- `news_events` contains only evidence-backed observations. Zero synthetic rows.
- Add `causal_event_key TEXT` to `news_events` (LLM-populated, nullable).
- Fix `sweep_fading_resolved()` unreachable `RESOLVED` by querying `news_event_state.last_real_seen_at` rather than the 30d window bucket.

## Touches

- `agents/news/intelligence.py` — `compute_trend()`, `sweep_fading_resolved()` → `update_event_state_sweep()`, `persist_events()`, extraction prompt (add `causal_event_key` field)
- `agent_db.py` — `news_event_state` table in `_new_cols`
- `portfolio_ai.py` — `_init_ai_tables()` for new table
- `tests/test_news_intelligence.py` — prove synthetic state cannot inflate trend counts; prove RESOLVED is reachable

## Done when

- [ ] `causal_event_key` is extracted by LLM and persisted on `news_events`
- [ ] `compute_trend()` counts distinct `causal_event_key` values (not fingerprints)
- [ ] `news_event_state` table exists and holds ACTIVE/FADING/RESOLVED per ticker+causal_event_key
- [ ] `news_events` contains no synthetic decay-marker rows
- [ ] `RESOLVED` state is reachable and tested
- [ ] A FADING sweep row from yesterday does not inflate today's `n30` occurrence count
