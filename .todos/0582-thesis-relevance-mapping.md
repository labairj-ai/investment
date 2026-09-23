# Map News Events to Thesis Pillars, Risks, and Catalysts

- **ID:** 0582
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0581

## Problem

News analysis currently produces "new customer win" or "guidance raised" without connecting the event to why it matters for the investment thesis. The system already stores thesis pillars, key risks, catalysts, qualitative signals, review triggers, and ADD/TRIM/EXIT conditions in the Thesis Monitor. These are never consulted during news analysis, so the user has to manually reason about relevance every time.

## Proposed approach

- For each structured event (from 0581), retrieve the holding's thesis pillars, key risks, catalysts, and review triggers from the Thesis Monitor.
- Ask the LLM to map the event against each relevant thesis component and return: which pillar/risk/catalyst is affected, whether the event strengthens or weakens it, and whether any review trigger has been tripped.
- Persist the mapping: `event_id → pillar_id / risk_id / catalyst_id`, `direction`, `magnitude`, `explanation`.
- Surface the mapping prominently in the dashboard output: e.g. "↑ Strengthens 'AI / Data Center Demand' pillar · Catalyst match: hyperscaler capex · No exit trigger affected."
- If an event directly touches a review trigger or ADD/TRIM/EXIT condition, flag it as `TRIGGER_PROXIMITY: HIGH`.

## Touches

- `agents/news/` — thesis lookup and mapping step
- Thesis Monitor DB tables — read-only access from news pipeline
- Dashboard — thesis impact section per event/ticker

## Done when

- [x] Every material news event is mapped to at least one thesis component (pillar, risk, catalyst, or trigger) when a match exists
- [x] Events that don't map to any thesis component are labeled THESIS_NEUTRAL rather than omitted
- [x] Review triggers and ADD/TRIM/EXIT conditions that are relevant to an event are surfaced with `TRIGGER_PROXIMITY` flag
- [x] Dashboard shows thesis impact statement per ticker, not just a prose summary
- [x] Mapping is persisted per event so it can be referenced in Briefing Agent and Decision Episodes (0586)

## Outcome

`agents/news/intelligence.map_thesis_relevance()` does keyword-based matching from event type → pillar/risk descriptions using `_EVENT_KEYWORDS` table. Returns `thesis_relevance` (0.0-1.0), `pillar_name`, `risk_name`, `catalyst_name`, `trigger_proximity`. Pillar importance scales the relevance score. VIOLATED/WARNING pillar status sets `trigger_proximity` to 1.0/0.5. Stored in `news_events` table. Dashboard's Thesis Impact section shows which pillar/risk is affected.
