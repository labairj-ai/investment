# Use Current Structured News Intelligence in Decision Brief

- **ID:** 0624
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0618

## Problem

`build_portfolio_brief_state()` calls `get_accepted_news_events()`, which returns the entire calibration corpus since acceptance — meaning old events accumulate indefinitely. As weeks go by, three-week-old news will continue appearing as current portfolio context. Additionally, the brief strips the fields that make News Intelligence valuable (`trend_status`, `signal_strength`, `portfolio_priority`, `confirmation_class`, `event_trigger_state`, `event_trigger_proximity`, `causal_driver`) and then re-classifies signals using incorrect type checks: it looks for `event_type in ("MULTI_SIGNAL", "ACCELERATING")`, but `MULTI_SIGNAL` is a `confirmation_class` and `ACCELERATING` is a `trend_state`, not an `event_type`. As a result, positive signals almost never reach Opportunities.

## Proposed approach

- Create `get_current_news_intelligence(conn, accepted_version='v2')` — a new query that returns only active/current signals using `news_event_state` (e.g. `current_state IN ('ACTIVE', 'ESCALATED', 'RECENTLY_RESOLVED')`) plus a recency window (e.g. last N days). Do not change `get_accepted_news_events()` — it correctly serves calibration.
- Replace the brief's crude opportunity/attention classifier in `build_portfolio_brief_state()` with proper consumption of the full v2 field set: `signal_strength`, `direction`, `trend_status`, `confirmation_class`, `thesis_relevance`, `trigger_proximity`, `portfolio_priority`, `causal_driver`.
- Opportunity classification: use `direction=POSITIVE` + `signal_strength >= threshold` + `confirmation_class=MULTI_SIGNAL` or `trend_status=ACCELERATING` or `portfolio_priority=HIGH`.
- Attention classification: use `direction=NEGATIVE` or `RISK` + `signal_strength` + `trigger_proximity` to determine severity.
- News signals in `brief_state` should carry all v2 interpretation fields, not just `event_type/direction/magnitude/confidence/thesis_relevance`.

## Touches

- `portfolio_ai.py` — new `get_current_news_intelligence()`; update `build_portfolio_brief_state()` to call it; fix opportunity/attention classification logic
- `agents/news/intelligence.py` — reference for field names and `news_event_state` schema
- `generate_dashboard.py` — may need to consume new fields (e.g. `signal_strength`, `trend_status`) if rendered in the brief card
- `tests/` — test that old events are excluded; test that `MULTI_SIGNAL` confirmation_class routes to Opportunities

## Done when

- [ ] `build_portfolio_brief_state()` calls `get_current_news_intelligence()` instead of `get_accepted_news_events()` for briefing signals
- [ ] Old/resolved events do not appear in `news_signals` — only current/active signals are included
- [ ] `news_signals` entries carry `signal_strength`, `trend_status`, `confirmation_class`, `portfolio_priority`, `trigger_proximity`, `causal_driver`
- [ ] A `MULTI_SIGNAL` confirmation class event routes to `opportunities`, not silently ignored
- [ ] An `ACCELERATING` trend_status event routes correctly based on direction
- [ ] `get_accepted_news_events()` is unchanged
- [ ] Tests cover: recency filter excludes stale events; MULTI_SIGNAL → opportunity; NEGATIVE + HIGH signal_strength → attention
