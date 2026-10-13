# Eastern-Time Dashboard Rendering

- **ID:** 0672
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0671

## Problem

The dashboard displays raw UTC timestamps throughout (Portfolio Brief, news intelligence, learning lab, recommendation views, trade history, etc.). Dates around UTC midnight display as the wrong Eastern calendar date. Users reviewing market-day activity must mentally translate times.

## Proposed approach

Audit all timestamp displays in `generate_dashboard.py` and any frontend JS/HTML templates:
- main dashboard
- Learning Lab, Champion/Challenger views
- opportunity/recommendation views
- trade/fill history
- news intelligence
- Portfolio Brief
- macro status, model lifecycle
- canary/system-health displays

Display standard:
- Full context: `"Sep 24, 2026 · 8:42 PM EDT"`
- Dense tables: `"09/24/26 8:42 PM EDT"`

Sorting must use canonical UTC values, not formatted display strings. No raw UTC timestamps in standard user-facing views.

## Touches

- `generate_dashboard.py` — all timestamp rendering sites
- Frontend JS/Jinja templates if used

## Done when

- [x] No raw UTC timestamps appear in standard user-facing dashboard views
- [x] Eastern timezone abbreviation is shown where ambiguity matters
- [x] Dates around UTC midnight display as the correct Eastern calendar date
- [x] DST boundaries display correctly
- [x] Sorting uses canonical timestamps, not formatted display strings
## Outcome

Implemented as part of 0668-0680 batch commit.
