# Finish Confirmation Quality: Event-Specific Fundamentals and Agent Findings

- **ID:** 0604
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0598, 0600

## Problem

Two confirmation channels are incomplete. (a) `_get_fundamentals_trend()` compares the latest quarterly revenue against the prior quarter with a ±3% threshold. Sequential QoQ comparison is noisy for seasonal businesses and is not event-sensitive — it gives the same signal for a MARGIN event as for a CAPEX event, when the relevant financial metric differs. (b) `_get_agent_findings_flag()` always returns `None`, so the AGENT_FINDINGS channel never casts a vote. Until it is wired to real Guardian or specialist-agent output, MULTI_SIGNAL_CONFIRMATION is structurally harder to reach via five independent channels, which is the design intent of 0600.

## Proposed approach

**Fundamentals channel (event-specific):**
Select the comparison metric based on `event_type`:
- `DEMAND`, `GUIDANCE_CHANGE`, `EARNINGS` → YoY revenue growth (same quarter last year vs current quarter)
- `MARGIN`, `PRICING` → gross margin or operating margin trend (YoY preferred)
- `CREDIT_DEBT` → debt-to-equity or interest coverage trend
- `CAPEX` → capex as % of FCF trend
- All others → fall back to YoY revenue as a generic signal, or return None

Use YoY quarterly comparison (Q vs same Q prior year) rather than sequential QoQ wherever company_financials has sufficient history. This requires at least 5 quarters of data; return None if history is insufficient.

**Agent findings channel:**
- Wire to a real source before marking 0600 done. Candidate sources: Guardian watchlist flags stored in a DB table, a specialist `news_events`-adjacent agent output table, or a lightweight flag column on `investment_theses`.
- Independence requirement: the finding timestamp or source must predate or be independent of the current news articles. If a Guardian agent consumes the same news articles, its output is not an independent vote — it is just the same source once removed. Enforce this by checking that the finding was recorded before the current `captured_at` timestamp of the snapshot.
- Store `{"source": "guardian", "flagged_at": "...", "reason": "..."}` in `confirmation_signals["agent_findings"]` for auditability.

**Instrumentation note (not a done criterion):** Once `causal_event_key` has been in production for 2+ weeks, measure `causal_key_churn_rate`: for events with the same `(ticker, event_type, direction)` and overlapping `article_ids` across days, how often does the LLM produce a different key? If churn is meaningful, a canonical-key resolver may be warranted. Do not build it speculatively.

## Touches

- `agents/news/intelligence.py` — `_get_fundamentals_trend()` (event-type dispatch, YoY logic), `_get_agent_findings_flag()` (wire real source), `attach_confirmation()` (auditability in signals dict)
- `tests/test_news_intelligence.py` — MARGIN event uses margin metric not revenue; DEMAND uses revenue; agent findings independence check

## Done when

- [x] `_get_fundamentals_trend()` selects the metric by `event_type`; DEMAND/EARNINGS/GUIDANCE use YoY revenue; MARGIN/PRICING use margin trend
- [x] YoY comparison used when ≥5 quarters of history available; returns None otherwise
- [x] `_get_agent_findings_flag()` reads a real persistent source (Guardian flags or equivalent), not always None
- [x] Agent finding independence check: finding timestamp predates or is independent of snapshot `captured_at`
- [x] `confirmation_signals["agent_findings"]` includes source and timestamp when a finding is present
- [x] All four criteria above covered by tests
