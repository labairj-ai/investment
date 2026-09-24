# Add Delta Tracking and Freshness to Decision Brief

- **ID:** 0622
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0619, 0620

## Problem

The current briefing repeats all portfolio state on every refresh, making it hard to distinguish new information from persistent background conditions. A thesis that has been at WARNING for a week looks identical to one that just dropped 15 points this morning. There is also no explicit freshness signal: the dashboard does not show which data sources are current, which are stale, or whether a degraded system is affecting the briefing's completeness.

## Proposed approach

- **Delta computation in `build_portfolio_brief_state()`:** When a prior brief snapshot exists in `portfolio_brief_snapshots`, diff the new state against it. Populate the `changes` array with items that are genuinely new or escalated since the last brief:
  - Thesis health score changed by ≥ threshold (e.g. ±5 points)
  - Pillar status changed (OK → WARNING, WARNING → VIOLATED)
  - News signal appeared, escalated, or resolved
  - Guardian finding opened or closed
  - Recommendation created, Critic verdict changed, or lifecycle advanced
  - Macro score moved outside prior band
  Items unchanged since last brief are moved to `watch_items`, not `attention_items`, unless still above the attention threshold.
- **Freshness block:** Each source in `freshness` carries `last_updated` (epoch), `age_hours`, `is_stale` (bool), and `status` (CURRENT / STALE / DEGRADED / UNAVAILABLE). Aggregate to an overall `freshness.overall` flag. If a source is DEGRADED or UNAVAILABLE, its contributions to `attention_items` are annotated with a caveat.
- **Briefing Agent uses delta:** Pass the `changes` array explicitly in the prompt so the LLM leads with new information. The prompt should say "these items are new since the last brief" vs. "these items were already flagged."
- **Brief snapshot retention:** Keep the last N brief snapshots (e.g. 30 days) in `portfolio_brief_snapshots` so delta can be computed across multiple periods if needed.

## Touches

- `portfolio_ai.py` — `build_portfolio_brief_state()` delta logic; snapshot retention policy in `portfolio_brief_snapshots`
- `agents/briefing_agent.py` — prompt updated to distinguish new vs. persisting items
- `generate_dashboard.py` — render `changes` as "New since last brief" label; render freshness footer with per-source indicators
- `tests/` — delta test: seeded "previous" snapshot + modified "current" state → expected `changes` entries

## Done when

- [ ] `changes` array is populated with items that differ from the most recent prior snapshot
- [ ] Items unchanged since last brief do not appear in `attention_items` unless still meeting attention threshold
- [ ] Each item in `attention_items` and `opportunities` carries `is_new` (bool) and `since` (ISO date of first appearance)
- [ ] `freshness` block has per-source `last_updated`, `age_hours`, `is_stale`, `status`
- [ ] Degraded/unavailable sources annotate their contributed items with a caveat
- [ ] Dashboard renders "New since last brief" label on new items
- [ ] Test: prior snapshot + changed thesis score → `changes` contains the thesis delta
