# Redesign Decision Journal UI Layout

- **ID:** 0133
- **Status:** done
- **Created:** 2026-09-08
- **Priority:** normal
- **Depends:** none

## Problem

The Decision Journal on the Decisions tab has been reorganized into day-based accordions, which is a big improvement, but the inner layout is still a dense flat table. With 500+ generated decisions, the journal is the primary record of agent + user activity and deserves a richer, more scannable UI — especially for days with many superseded/vetoed entries that create visual noise.

## Proposed approach

- **Day accordion header mini-summary** — add inline status chips to each day header (e.g., "4 accepted · 2 vetoed · 8 superseded") so you can judge a day at a glance without opening it. Could also tint the header stripe slightly by dominant outcome.
- **Card layout inside each day** — replace the table rows with compact cards (2-column grid or single column). Each card: ticker + action type as the title, status badge prominent, return / opp-cost as highlighted numbers, reason + notes inline. Removes the awkward `col-hide-sm` responsive hack.
- **Superseded entries visually muted** — superseded rows dominate the list (86 of 503). Show them in a lighter style or collapse them into a "show N superseded" toggle within each day, so accepted/rejected decisions stay prominent.
- **Filter bar above the accordion list** — single-row pill filters: All | Accepted | Rejected | Deferred | Vetoed | Superseded. Toggling a filter collapses/hides days with no matching entries and only shows matching cards.
- **Collapse-all / Expand-all controls** — small text buttons next to the section header for power users.
- Open question: should cards replace the table entirely, or keep a compact table with a card detail panel on click?

## Touches

`generate_dashboard.py` — `_renderDJTable`, `_djToggleDay`, and the `dj-table-wrap` section. No backend changes needed.

## Done when

- [ ] Each day accordion header shows a per-status mini-summary without opening it
- [ ] Superseded entries are visually de-emphasized or grouped behind a toggle
- [ ] A status filter bar lets the user show only accepted/rejected/etc entries across all days
- [ ] Layout reads clearly on a narrow viewport without hidden columns
