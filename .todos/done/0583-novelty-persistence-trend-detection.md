# Add Novelty, Persistence, and Trend Detection to News Events

- **ID:** 0583
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0581

## Problem

A single negative article is often noise. Three related events over six weeks are a pattern. The system currently treats each day's news independently, so an emerging risk that has been accumulating for weeks looks identical to a one-off mention. There is no way to distinguish a new signal from a confirming recurrence of an already-known concern.

## Proposed approach

- Maintain per-ticker event history in the DB. For each new event, compare against the prior 7/30/90-day baseline for the same event type and direction.
- Calculate a trend status for each event: `NEW` (first occurrence of this event type/direction), `CONFIRMING` (same direction as prior occurrences), `ACCELERATING` (more frequent than baseline), `REVERSING` (direction changed from recent trend), `FADING` (lower frequency or magnitude than recent baseline), `RESOLVED` (prior concern no longer appearing).
- Add occurrence counts and first/last-seen dates. Example output: "Margin pressure: 3 confirming events in 21 days; previously isolated → now ACCELERATING."
- `ACCELERATING` and `REVERSING` events warrant higher materiality weight in 0584.
- Store trend_status, occurrence_count_7d, occurrence_count_30d, occurrence_count_90d alongside each event.

## Touches

- `agents/news/` — trend calculation against event history
- DB schema — event history table with occurrence tracking
- Dashboard — trend badge per event (NEW / CONFIRMING / ACCELERATING / etc.)

## Done when

- [x] Each event is assigned a trend status based on comparison against 7/30/90-day event history
- [x] Occurrence counts at three horizons are persisted per event
- [x] `ACCELERATING` events on thesis-relevant risks or pillars are surfaced with a distinct visual indicator
- [x] A `REVERSING` trend (concern fading after prior elevation) is detectable and labeled
- [x] First occurrence of a genuinely new event type is labeled `NEW` rather than inheriting stale context

## Outcome

`agents/news/intelligence.compute_trend()` queries `news_events` for prior occurrences at 7/30/90-day windows. Logic: no prior → NEW; opposite direction in 30d → REVERSING; 2+ in 7d and 3+ in 30d → ACCELERATING; 2+ in 30d → CONFIRMING; prior in 90d but not 30d → FADING. Counts stored in `occurrence_count_7d/30d/90d`. Dashboard renders badge per event (gold for ACCELERATING, purple for NEW, etc.).
