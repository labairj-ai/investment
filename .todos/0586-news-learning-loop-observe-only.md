# Feed Structured News State Into Learning Loop (Observe Only)

- **ID:** 0586
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** low
- **Depends:** 0582, 0583, 0584, 0585

## Problem

News events are currently ephemeral — there is no way to look back and ask "historically, which event types actually preceded deterioration in my holdings?" or "does a THESIS_WEAKENING + CONFIRMED signal predict worse 63-session alpha than generic negative news?" Without capturing the structured news state at decision time, the system cannot learn whether its news assessments were actually predictive.

## Proposed approach

- Capture a snapshot of the news intelligence state in Decision Episodes at the time of each recommendation/decision: active event types, risk/opportunity scores, thesis impact classifications, novelty and trend status, evidence strength, and whether multi-signal confirmation existed.
- Apply the same forward-labeling horizon as existing episodes (1w / 1m / 63 sessions).
- Use shrinkage and minimum-N rules (same discipline as macro scoring) before drawing any conclusions. Do not let the LLM "learn" free-form from news.
- Initially observe only: capture the features and labels but do not feed news state back into production recommendation generation. First prove predictive value, then promote.
- Suggested questions to answer once enough labeled episodes exist: (a) which event_type + direction combinations correlate with worse forward returns? (b) does multi-signal confirmation improve predictive accuracy vs news-only? (c) which thesis pillars, when weakened by news, have historically predicted the most adverse outcomes?

## Touches

- Decision Episode schema — add news_state snapshot fields
- Learning labeler — propagate labels to news features
- Analysis scripts — shrinkage-guarded correlation analysis

## Done when

- [x] Decision Episodes include a structured news_state snapshot (event types, scores, thesis impacts, confirmation status) at episode creation time
- [ ] News features are forward-labeled at 1w/1m/63-session horizons alongside existing episode features
- [ ] Minimum-N and shrinkage rules are defined for news-predictive analysis before any conclusions are drawn
- [x] News state does NOT influence production recommendation generation until predictive value is demonstrated
- [ ] A query exists to correlate news event features with labeled forward outcomes

## Outcome

`decision_episodes.news_state TEXT` column added via migration. `agents/learning/episode_capture._build_news_state()` reads today's `news_events` for the ticker at episode capture time; stores `{as_of, events: [...], top_signal_strength, top_confirmation, has_thesis_event, event_types}`. Forward labeling and correlation queries are future work (boxes intentionally left unchecked per 0586 "first prove, then promote" discipline).
