# Market Schedules Use America/New_York

- **ID:** 0675
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** none

## Problem

Market-related schedules and gates are defined as fixed UTC offsets (e.g. `14:45 UTC` for the 09:45 ET gate) or hardcoded `"EST"`. These break silently on DST transitions: during summer the 09:45 gate fires at 13:45 UTC rather than 14:45, or vice versa depending on which offset was chosen. The correct approach is `America/New_York` so DST is handled automatically.

## Proposed approach

Audit all market-schedule definitions:
- 09:45 market gate
- 12:00 market gate
- 15:45 market gate
- market-open / market-close logic
- daily outcome labeling
- maintenance tasks tied to market sessions
- report-generation schedules tied to trading hours

Replace fixed UTC offsets and `"EST"`/`"EDT"` strings with `ZoneInfo("America/New_York")` and express the target time in local Eastern terms. Let the library resolve the UTC equivalent at runtime.

Never encode market schedules as `14:45 UTC`, `13:45 UTC`, fixed `"EST"`, or fixed `"EDT"`.

## Touches

- `serve.py`, `portfolio_ai.py`, systemd/launchd timer definitions, any scheduler config
- `time_utils.py` — `TZ_EASTERN` from 0668

## Done when

- [x] Market timers use `America/New_York`
- [x] Winter (EST) schedule resolves correctly
- [x] Summer (EDT) schedule resolves correctly
- [x] DST changes require no manual configuration
- [x] Tests verify equivalent market-local trigger times across EST and EDT
## Outcome

Implemented as part of 0668-0680 batch commit.
