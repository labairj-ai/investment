# Define the Canonical Time Contract

- **ID:** 0668
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** none

## Problem

The investment platform has no explicit system-wide timestamp contract. Subsystems independently choose between UTC, local time, and fixed EST/EDT offsets, creating inconsistency in ordering, audit, and learning calculations. All persisted timestamps should be UTC; all user-facing timestamps should be in "America/New_York"; DST should be handled automatically via ZoneInfo, never by hard-coded offsets.

## Proposed approach

Create a central time utility module (e.g. `time_utils.py`) that defines:
- `TZ_UTC` — `ZoneInfo("UTC")`
- `TZ_EASTERN` — `ZoneInfo("America/New_York")`
- Canonical persisted format: timezone-aware ISO-8601 UTC
- User-facing display format: Eastern Time with correct EST/EDT abbreviation

Document explicitly:
- Storage timezone = UTC
- Display timezone = America/New_York (DST-aware)
- Fixed `-05:00` / `-04:00` offsets and hardcoded `"EST"` strings are prohibited
- Historical timestamps are excluded from rewrite — compatibility handled separately in 0677

## Touches

- New file: `time_utils.py` (or `utils/time_utils.py`)
- `README.md` or inline module docstring documenting the contract

## Done when

- [x] A central time utility module exists
- [x] `UTC` and `America/New_York` timezone objects are defined centrally
- [x] Timestamp contract is documented in code
- [x] Documentation explicitly distinguishes storage time from display time
- [x] Historical timestamps are explicitly excluded from migration/rewrite
- [x] DST behavior is documented
## Outcome

Implemented as part of 0668-0680 batch commit.
