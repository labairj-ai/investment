# Build Canonical Time Utilities

- **ID:** 0669
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0668

## Problem

Timestamp creation and conversion is scattered across the codebase with no shared helpers. Each call site independently chooses formats, timezones, and parsing approaches, making drift inevitable. A shared set of functions with well-defined contracts is needed so behavior cannot diverge between subsystems.

## Proposed approach

Implement in the central time utility module from 0668:

- `now_utc()` → timezone-aware UTC datetime
- `now_utc_iso()` → UTC ISO-8601 string (e.g. `"2026-09-25T00:42:15Z"`)
- `epoch_to_utc(ts)` → timezone-aware UTC datetime from Unix timestamp
- `parse_timestamp(s)` → timezone-aware UTC datetime; accepts Z-suffix, explicit UTC offsets, and legacy naive strings only via an explicitly documented compatibility path; unknown formats fail visibly
- `to_eastern(dt)` → convert UTC-aware datetime to `ZoneInfo("America/New_York")` (correctly selects EST or EDT)
- `format_eastern(dt)` → human-readable Eastern string with abbreviation

All functions must refuse naive datetime inputs silently — they must either require awareness or raise explicitly.

## Touches

- `time_utils.py` — implement all six functions
- `tests/test_time_utils.py` — full test suite (see acceptance criteria)

## Done when

- [x] New UTC timestamps are timezone-aware
- [x] UTC serialization produces an unambiguous UTC value
- [x] Eastern conversion uses `ZoneInfo`
- [x] Tests cover EST (e.g. Jan 15)
- [x] Tests cover EDT (e.g. Jul 15)
- [x] Tests cover spring-forward transition (2nd Sunday March)
- [x] Tests cover fall-back transition (1st Sunday November)
- [x] Tests cover `"Z"`-suffix input
- [x] Tests cover explicit UTC-offset input
- [x] Naive inputs cannot silently be interpreted as local time
## Outcome

Implemented as part of 0668-0680 batch commit.
