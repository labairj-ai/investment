# Eastern-Time API Presentation Layer

- **ID:** 0671
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0669

## Problem

API responses return raw UTC timestamps for fields intended for direct human consumption. Users must mentally convert UTC to Eastern, which is error-prone and misaligns with the market-day mental model. The fix is to expose Eastern-converted timestamps on presentation fields while keeping canonical UTC available for audit/debug use.

## Proposed approach

For API fields intended for direct presentation, add an `_et` companion field:

```json
{
  "captured_at": "2026-09-25T00:42:15Z",
  "captured_at_et": "2026-09-24T20:42:15-04:00"
}
```

Use `to_eastern()` + `format_eastern()` from the canonical time utilities. Never manually subtract 4 or 5 hours. Keep raw UTC on audit-sensitive objects (provenance, trade records). Audit `serve.py` route handlers for all timestamp fields returned to the frontend.

## Touches

- `serve.py` — add `_et` fields to presentation API responses
- `time_utils.py` — `to_eastern()`, `format_eastern()` (from 0669)
- `tests/` — API responses render EDT during daylight time, EST during standard time

## Done when

- [x] User-facing API times render as `America/New_York`
- [x] Raw UTC remains available for audit-sensitive objects
- [x] EDT displays correctly during daylight time
- [x] EST displays correctly during standard time
- [x] API conversion never changes the underlying instant
- [x] No API code manually subtracts four or five hours
## Outcome

Implemented as part of 0668-0680 batch commit.
