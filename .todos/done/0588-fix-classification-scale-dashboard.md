# Fix Classification Scale and Dashboard Correctness

- **ID:** 0588
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0587

## Problem

The dashboard uses `portfolio_priority >= 45` to classify events into Emerging Risk/Opportunity buckets. Because `portfolio_priority` scales by position size, a high-signal event in a small holding (e.g., 2% weight) will almost never reach 45, making the buckets nearly empty for typical portfolios. The Thesis bucket uses direction alone rather than actual thesis relevance. The "Nothing Material Changed" bucket renders expanded instead of collapsed. The Watch Next section in `_renderIntelCard()` is a stub with no content. Only the top event per ticker is rendered; users miss the second and third most important events.

## Proposed approach

- Swap bucket classification thresholds to use `signal_strength` (absolute event quality, 0–100) instead of `portfolio_priority`. `portfolio_priority` stays as the sort key within each bucket.
- Thesis bucket: classify event into Thesis Changes when `thesis_relevance > 0` (e.g., > 0.25) or `trigger_proximity == true`, not based on direction.
- Initialize "Nothing Material Changed" `<div>` with `class="news-bucket news-bucket-nothing collapsed"` so the CSS `collapsed` rule hides the body on load.
- Implement Watch Next section: use `expected_horizon`, `event_type`, and `trend_status` to generate a one-line forward indicator string (e.g., "Watch for next earnings to confirm demand recovery").
- Render top 2–3 events per ticker rather than stopping at one.

## Touches

- `generate_dashboard.py` — `_renderNewsBody()`, `_renderIntelCard()`, bucket threshold constants (`_EMERGING_RISK_THRESH`, `_EMERGING_OPP_THRESH`, `_THESIS_THRESH`), CSS for `.news-bucket-nothing`.

## Done when

- [ ] Emerging Risk and Opportunity buckets populate for events with `signal_strength >= threshold` regardless of position size
- [ ] `portfolio_priority` is used only for ordering within buckets, not for bucket assignment
- [ ] Thesis Changes bucket fires when `thesis_relevance > 0.25` or `trigger_proximity` is set
- [ ] "Nothing Material Changed" bucket starts collapsed (body hidden) on page load
- [ ] Watch Next section renders a meaningful forward indicator string per event
- [ ] Top 2–3 events per ticker are rendered (not just one)
