# Replace AI Insight Card with Decision-Oriented Brief UI

- **ID:** 0621
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0620

## Problem

The current "AI Portfolio Insight" card is framed as a general AI analysis and placed below Holdings News on the Portfolio tab — requiring the user to read the news feed before understanding the portfolio. Its sections (Macro Summary, Risk Flags, Tax Note, Key Question) do not map to the five questions a decision-oriented briefing should answer: what changed, what needs attention, what opportunities appeared, what is being watched, and what is the confidence in this briefing. Items are not linkable to their source features, and there is no structural separation between risks and opportunities.

## Proposed approach

- **Rename the card** from "AI Portfolio Insight" to "Portfolio Decision Brief" (or similar).
- **Move it to the top of the Portfolio tab**, above Holdings News. The relationship should be: Decision Brief = what matters; Holdings News = evidence/details.
- **Replace the section structure** with five named sections:
  1. **What Changed** — 2–5 bullets summarizing new information since the last brief (thesis score deltas, new/resolved news signals, new Critic-approved recommendations). Nothing that was already shown last time unless it escalated.
  2. **Needs Attention** — ranked queue of risk/decision items. Each item shows: ticker, signal type, supporting evidence from ≥1 subsystem, and a direct link to the originating feature (Thesis, Decisions, Covered Call, News). Guardian + Thesis + News multi-signal items ranked highest.
  3. **Opportunities** — separate from risks. Positive signals: Emerging Opportunity news events, ACCELERATING/MULTI_SIGNAL thesis-relevant items, Opportunity Hunter flags. Each linkable to source.
  4. **Watch / No Action** — items the system is tracking but that do not require a decision. This section tells the user when *not* to act. Include: news signals below confirmation threshold, macro sensitivities without recommendations, allocations within policy bands.
  5. **Evidence Footer** — one line: agent count, current recommendations, accepted news event count, data freshness status, news intelligence version, learning mode, last pipeline time. Gives confidence in where the answer came from.
- **Remove the "Refresh Holdings News first…" notice** — the briefing pipeline should detect whether news is current and either consume the accepted snapshot or display "News intelligence stale / unavailable" itself.
- **Render the stable-state message cleanly:** When nothing meaningful happened, show a compact summary like "Portfolio stable. No decisions required." rather than a full five-section layout with empty sections.

## Touches

- `generate_dashboard.py` — Portfolio tab layout; new card sections; link targets; evidence footer
- `serve.py` — API endpoint serving the briefing result to the dashboard
- `agents/briefing_agent.py` — output must match the five-section schema (from 0620)
- CSS / JS in the dashboard template — styling for the ranked attention queue; stable-state condensed view

## Done when

- [ ] "Portfolio Decision Brief" card appears at the top of the Portfolio tab, above Holdings News
- [ ] Card has five named sections: What Changed, Needs Attention, Opportunities, Watch/No Action, Evidence Footer
- [ ] Each Needs Attention and Opportunities item is linkable to its originating feature tab/section
- [ ] Stable-state (no action required) renders as a compact summary, not five empty sections
- [ ] Evidence footer shows agent count, recommendation count, news event count, freshness, version, last pipeline time
- [ ] "Refresh Holdings News first" notice is removed; briefing self-reports news staleness if relevant
- [ ] Risks and opportunities are in separate sections (not mixed)
