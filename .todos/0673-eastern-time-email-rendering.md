# Eastern-Time Email and Brief Rendering

- **ID:** 0673
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0669

## Problem

Automated briefs and email notifications render UTC timestamps in human-readable prose, misaligning with the market day and requiring mental conversion by the reader.

## Proposed approach

Audit all email generation and brief rendering paths:
- morning briefs
- portfolio alerts
- system warnings
- outcome summaries
- learning reports
- execution notifications
- maintenance/error emails

Replace raw UTC timestamp rendering with `format_eastern()` from the canonical time utilities. UTC may remain available in technical diagnostic payloads where useful (labeled explicitly). User-facing prose must never expose a raw UTC timestamp unless explicitly labeled as UTC.

## Touches

- Email generation scripts / agent briefing output paths
- `time_utils.py` — `format_eastern()` (from 0669)

## Done when

- [x] Email timestamps display in Eastern Time
- [x] EST/EDT rendered correctly
- [x] UTC remains available in technical diagnostic payloads where useful
- [x] User-facing prose never exposes a raw UTC timestamp unless explicitly labeled
## Outcome

Implemented as part of 0668-0680 batch commit.
