# Tighten parse_timestamp() Legacy Compatibility

- **ID:** 0683
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0669

## Problem

`parse_timestamp()` currently accepts any naive ISO datetime string and silently treats it as UTC. A value accidentally persisted tomorrow as `"2026-09-25T14:30:00"` (canonical T-separator, no offset, no Z) would pass through as 14:30 UTC — no error raised. This defeats the fail-closed intent. The canary would also accept it without complaint.

The generic parser should not silently promote arbitrary naive T-separator timestamps. Only explicitly documented historical formats should receive the UTC-assumption treatment.

## Proposed approach

In `parse_timestamp()`:

1. **Z-suffix** (`"2026-09-24T23:49:21Z"`) → UTC. Keep as-is.
2. **Explicit offset** (`"2026-09-25T14:30:00+00:00"`, `"-04:00"` etc.) → parse offset as-is, convert to UTC. Keep as-is.
3. **Known legacy space-separator** (`"2026-09-24 23:49:21"` — no T, no offset) → treat as UTC (explicitly documented, tested, used by `ai_insights.generated_at` pre-0667). Keep as explicit compat path with a comment.
4. **T-separator without Z or offset** (`"2026-09-25T14:30:00"`) → **raise `ValueError`** with a message pointing to the contract. This was previously silently treated as UTC; it must now fail visibly.

Add a `legacy_utc=False` keyword argument that callers can pass to opt into treating the naive string as UTC — this is the explicit escape hatch for callers that genuinely need it, and it requires a comment at the call site justifying the exception.

Add or update tests:
- `"2026-09-25T14:30:00"` (no Z, no offset) → raises `ValueError`
- `"2026-09-25T14:30:00"` with `legacy_utc=True` → returns 14:30 UTC (explicit opt-in works)
- `"2026-09-24 23:49:21"` (space sep) → UTC (legacy compat still works)
- `"2026-09-25T14:30:00Z"` → UTC (Z still works)
- `"2026-09-25T14:30:00+00:00"` → UTC (explicit offset still works)

Audit existing callers of `parse_timestamp()` across the codebase and fix any that inadvertently passed T-separator naive strings (they should either add Z or pass `legacy_utc=True` with a justification comment).

## Touches

- `time_utils.py` — tighten `parse_timestamp()`; add `legacy_utc=` keyword
- `tests/test_time_utils.py` — add failing and passing cases
- Any callers that depended on naive T-separator strings being silently accepted

## Done when

- [x] `"2026-09-25T14:30:00"` (no Z, no offset) raises `ValueError`
- [x] `legacy_utc=True` opt-in works and requires justification comment at call site
- [x] `"2026-09-24 23:49:21"` space-sep still parses as UTC (legacy compat)
- [x] Z-suffix and explicit-offset inputs still work
- [x] All existing callers audited; none silently depend on the old permissive behavior
- [x] Tests pass
