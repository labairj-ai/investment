# Extract Articles Into Structured Events Before LLM Summary

- **ID:** 0581
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0580

## Problem

Articles are currently summarized as prose. Multiple articles about the same underlying fact produce five signals instead of one clustered event. There is no controlled vocabulary for what kind of event is happening, so downstream analysis cannot distinguish a guidance cut from a customer win, or a one-time item from a structural change.

## Proposed approach

- Before asking the LLM for prose, extract each article into a structured event using a controlled taxonomy: `GUIDANCE_CHANGE`, `EARNINGS`, `MARGIN`, `DEMAND`, `CUSTOMER_WIN`, `CUSTOMER_LOSS`, `PRODUCT`, `CAPEX`, `M_AND_A`, `MANAGEMENT`, `REGULATORY`, `LITIGATION`, `SUPPLY_CHAIN`, `COMPETITOR`, `PRICING`, `CREDIT_DEBT`, `DIVIDEND_BUYBACK`, `MACRO_EXPOSURE`.
- Each event carries: `event_type`, `direction` (POSITIVE / NEGATIVE / MIXED / NEUTRAL), `expected_horizon` (IMMEDIATE / SHORT / MEDIUM / LONG), `magnitude` (LOW / MEDIUM / HIGH), `confidence`, `affected_metric`, `sources` (list), `first_seen`, `last_seen`, `evidence_text`.
- Cluster articles about the same underlying fact into one event. Multiple sources for the same event raise confidence; they do not create duplicate events.
- The prose LLM summary is generated from the clustered events, not raw articles. This makes the summary more coherent and reduces hallucinated connections between unrelated articles.

## Touches

- `agents/news/` — new event extraction step before summarization
- DB schema — event table per ticker per date with taxonomy fields
- `generate_news_summaries.py` — pipeline restructure

## Done when

- [x] Each article is classified into one of the defined event types with direction, horizon, magnitude, and confidence
- [x] Multiple articles about the same fact are merged into a single event cluster with source count and first/last seen
- [x] Event records are persisted to DB independently of the prose summary
- [x] Prose summary is generated from clustered events, not raw article text
- [x] Unknown or ambiguous events are flagged MIXED/NEUTRAL rather than silently dropped

## Outcome

`agents/news/intelligence.extract_events_llm()` runs a lean LLM pass (num_predict=3000) before prose generation. LLM output is a JSON dict `{TICKER: [{event_type, direction, magnitude, horizon, confidence, affected_metric, evidence, titles}]}`. Invalid event_types default to MACRO_EXPOSURE; invalid directions default to NEUTRAL. Events are stored in `news_events` table per-ticker per-day and deleted+reinserted on each refresh. Prose prompt now includes a structured events context block.
