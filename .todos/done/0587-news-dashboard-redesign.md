# Redesign News Dashboard Around Changes, Not Headlines

- **ID:** 0587
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0582, 0583, 0584, 0585

## Problem

The current dashboard organizes news by ticker and lists article summaries. Users have to scan every ticker to find out what changed, manually judge relevance and importance, and connect events to their thesis themselves. There is no "nothing material changed" bucket, no sort by portfolio priority, and no visual indicator of whether something is new versus a recurring theme.

## Proposed approach

Restructure the news view around four top-level buckets sorted by portfolio priority:
1. **Emerging Risks** — high-signal negative events, especially ACCELERATING or MULTI_SIGNAL_CONFIRMED
2. **Emerging Opportunities** — high-signal positive events
3. **Thesis Changes** — events that map directly to a pillar, catalyst, or trigger regardless of direction
4. **Nothing Material Changed** — tickers with no high-signal events (collapsed by default)

Per-ticker card structure (when expanded):
- Header: ticker, signal classification (EMERGING RISK / OPPORTUNITY / THESIS CHANGE / WATCH), signal strength, confidence, trend badge
- **What changed**: one-paragraph synthesis of the underlying development
- **Thesis impact**: pillar/risk/catalyst affected, direction, trigger proximity
- **Why it matters**: event type, horizon, occurrence count, trend status
- **Confirmation**: price vs SPY, pillar health, macro exposure, valuation note
- **Watch next**: one-line forward indicator (e.g., "Next earnings: confirm cloud revenue growth")
- **Evidence**: expandable list of article titles, sources, timestamps, source count

Portfolio theme alerts surface above the ticker list when 3+ holdings share a causal event type.

## Touches

- Dashboard frontend — complete view restructure of news section
- Backend news API — add signal_strength, portfolio_priority, thesis_impact, trend fields to response
- CSS/layout — new card structure with expandable evidence

## Done when

- [x] Default view shows Emerging Risks / Opportunities / Thesis Changes / Nothing Changed buckets sorted by portfolio_priority
- [x] Each ticker card shows What Changed, Thesis Impact, Why It Matters, Confirmation, Watch Next, and expandable Evidence
- [x] Portfolio theme alerts appear above the ticker list when applicable
- [x] "Nothing Material Changed" bucket is collapsed by default and shows ticker count only
- [x] Article-level evidence (title, source, timestamp) is accessible but not the primary display

## Outcome

`_renderNewsBody()` now takes `events` and `themes` as additional parameters. When structured events are present, renders 4 buckets (Emerging Risks / Opportunities / Thesis Changes / Watch) sorted by portfolio_priority. Legacy fallback for pre-event cache. Portfolio theme banners appear above buckets. Each ticker card has collapsed body with What Changed, Analysis, Thesis Impact, Why It Matters, Confirmation, and expandable evidence list. "Nothing Material Changed" bucket lists tickers without events, initially expanded (CSS `.news-bucket-nothing.collapsed .news-bucket-body` hides body). `/api/news-summary` response extended with `events`, `themes`, `news_hash` fields.
