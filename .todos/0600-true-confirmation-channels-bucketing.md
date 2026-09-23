# True Confirmation Channels and Per-Event Dashboard Bucketing

- **ID:** 0600
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0592, 0588

## Problem

Three bugs: (a) `alpha_1d` and `alpha_5d` each increment `corroborating` independently. They are two observations from the same price channel, not two independent signals. Today a NEGATIVE event can reach `MULTI_SIGNAL_CONFIRMATION` with only price + thesis health — two actual information sources, not three. (b) The `FUNDAMENTALS` and `AGENT_FINDINGS` confirmation channels from the 0592 spec were never implemented, making `MULTI_SIGNAL` harder to reach via genuine independent channels and defeating the purpose of the classification. (c) In the dashboard, secondary events for a ticker are all bucketed by the top event's `_bucketClass()`. A high-signal NEGATIVE regulatory risk event can land inside Emerging Opportunities if the ticker's top event is positive — hiding a genuine risk.

## Proposed approach

**Confirmation channels (each casts at most one vote):**
- `PRICE`: best of 1d/5d alpha (one vote regardless of how many spans confirm)
- `FUNDAMENTALS`: revenue-growth pillar trend from financial pipeline (e.g. gross_margin or revenue_growth direction over last 2 periods)
- `THESIS`: health score direction
- `MACRO`: rate sensitivity for rate-driven events
- `AGENT_FINDINGS`: flag from Guardian or other agents indicating flagged concern

`SOFT_CONFIRMATION` threshold stays at 1+ channels; `MULTI_SIGNAL` stays at 3+ channels — but now 3+ means three genuinely independent sources.

**Dashboard bucketing fix:**
- Each event is bucketed independently using its own `_bucketClass(dir, hasThesis, sig, triggerProx)`.
- Remove the "ticker bucket = top event bucket" logic from `_renderNewsBody()`.
- Initial implementation: individual event cards, each in its own bucket. If this creates duplicate ticker headers, add a lightweight `tickerOf(ev)` label inside the card (already present as `news-intel-ticker`).

**Version bump:**
- Before shipping this todo, check whether any production `news_events` rows carry `news_intelligence_version="v1"`. If so, bump `NEWS_INTELLIGENCE_VERSION = "v2"` in `intelligence.py` and add a one-line migration comment. Do not rewrite v1 rows.

## Touches

- `agents/news/intelligence.py` — `attach_confirmation()`, channel-vote logic, FUNDAMENTALS + AGENT_FINDINGS stubs
- `generate_dashboard.py` — `_renderNewsBody()` event bucketing loop
- `tests/test_news_intelligence.py` — price-as-one-channel test; MULTI_SIGNAL requires 3 independent channels; mixed-ticker test (positive top event does not hide negative secondary)

## Done when

- [ ] `alpha_1d` and `alpha_5d` together cast one PRICE vote, not two
- [ ] `FUNDAMENTALS` channel is implemented (revenue/margin trend, at least a stub that reads from financial pipeline)
- [ ] `AGENT_FINDINGS` channel is implemented (stub reads a flag from agent output if available)
- [ ] `MULTI_SIGNAL_CONFIRMATION` requires 3+ independent channels (price, fundamentals, thesis, macro, agent — each max one vote)
- [ ] Each event in `_renderNewsBody()` is bucketed by its own `signal_strength` and `direction`, not the ticker's top event
- [ ] A NEGATIVE high-signal event on a ticker whose top event is POSITIVE appears in Emerging Risks, not Emerging Opportunities
- [ ] `NEWS_INTELLIGENCE_VERSION` bumped to `"v2"` if v1 rows exist in production before this lands
