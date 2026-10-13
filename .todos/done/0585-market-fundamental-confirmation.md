# Attach Market and Fundamental Confirmation to News Events

- **ID:** 0585
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0584

## Problem

News becomes much more useful when the system asks whether other signals agree with it. A negative demand story is noise if price/alpha is flat and fundamentals are on trend. The same story paired with deteriorating revenue-growth pillar health and recent negative alpha is a confirmed deterioration. Currently all news events are treated as equally credible regardless of whether anything else corroborates them.

## Proposed approach

- For each ticker with a high-signal event, attach available confirmation signals: price vs SPY over 1d/5d/20d (alpha), abnormal volume flag if available, estimate/guidance change, recent financial metric trend (from financial pipeline), thesis-health score from Thesis Monitor, current macro exposure score, upcoming earnings proximity, and any relevant agent findings.
- Classify each event as one of: `NEWS_ONLY`, `SOFT_CONFIRMATION` (1–2 corroborating signals), `MULTI_SIGNAL_CONFIRMATION` (3+ corroborating signals), `CONTRADICTED` (news is negative but price/fundamentals are strong, or vice versa).
- A `MULTI_SIGNAL_CONFIRMATION` event should receive a materiality boost in the 0584 signal_strength formula.
- `CONTRADICTED` events should be surfaced with a skepticism note rather than suppressed.
- Also add a cross-holding portfolio theme detector: if 3+ holdings independently generate events of the same causal type (e.g., "AI capex slowdown", "dollar strengthening"), surface a `PORTFOLIO_THEME` alert with affected tickers, total portfolio weight, and event count.

## Touches

- `agents/news/` — confirmation assembly step
- Price/financial pipeline — read recent alpha and metric trends
- Thesis Monitor — read thesis-health scores
- Dashboard — confirmation badge and portfolio theme section

## Done when

- [x] Each high-signal event has a confirmation classification (NEWS_ONLY / SOFT / MULTI_SIGNAL / CONTRADICTED)
- [x] `MULTI_SIGNAL_CONFIRMATION` events receive a materiality boost in signal_strength
- [x] `CONTRADICTED` events are surfaced with a skepticism note, not suppressed
- [x] Portfolio theme detection fires when 3+ holdings share a causal event type in the same window
- [x] Portfolio theme alert shows affected tickers, combined weight, and event count

## Outcome

`attach_confirmation()` checks price alpha (1d/5d from holding_day+spy_prices), thesis health score, macro rate sensitivity. 1+ corroborating → SOFT, 3+ → MULTI_SIGNAL, contradicting > corroborating and ≥2 → CONTRADICTED with skepticism_note. `_CONFIRM_BOOST` multipliers (1.0/1.3/1.6/0.7) feed into signal_strength. `detect_portfolio_themes()` groups events by (event_type, direction) across tickers; fires alert when 3+ tickers share a type. Themes stored in `news_portfolio_themes` table and returned via API, rendered above ticker list in dashboard.
