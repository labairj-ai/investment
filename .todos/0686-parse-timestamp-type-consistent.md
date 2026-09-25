# Make parse_timestamp() Type-Consistent for Naive Inputs

- **ID:** 0686
- **Status:** backlog
- **Created:** 2026-09-25
- **Priority:** high
- **Depends:** 0683

## Problem

After 0683, `parse_timestamp()` rejects naive T-separator strings unless `legacy_utc=True` is passed. But it still silently promotes naive `datetime` objects to UTC with no guard:

```python
if isinstance(s, datetime):
    if s.tzinfo is None:
        return s.replace(tzinfo=TZ_UTC)   # no legacy_utc check
```

This gives two different safety contracts depending on Python type. A naive string `"2026-09-25T14:30:00"` is rejected; the equivalent `datetime(2026, 9, 25, 14, 30)` is silently accepted. A caller constructing a naive datetime and passing it to `parse_timestamp()` bypasses the protection added in 0683.

## Proposed approach

Apply the same `legacy_utc` guard to the datetime object branch:

```python
if isinstance(s, datetime):
    if s.tzinfo is None:
        if not legacy_utc:
            raise ValueError(
                "parse_timestamp: naive datetime object rejected. "
                "Add tzinfo or pass legacy_utc=True with a justification comment."
            )
        return s.replace(tzinfo=TZ_UTC)
    return s.astimezone(TZ_UTC)
```

Audit all callers of `parse_timestamp()` that may pass naive datetime objects — they should either attach tzinfo before calling, or pass `legacy_utc=True` with a comment documenting the assumption.

## Touches

- `time_utils.py` — add `legacy_utc` guard to `isinstance(s, datetime)` branch
- `tests/test_time_utils.py` — add: naive datetime raises without flag; naive datetime with `legacy_utc=True` returns UTC; aware datetime still converts correctly
- Any callers passing naive datetime objects (audit needed)

## Done when

- [ ] Naive `datetime` object without tzinfo raises `ValueError` unless `legacy_utc=True`
- [ ] Naive `datetime` with `legacy_utc=True` returns UTC-aware datetime
- [ ] Aware `datetime` input still converts to UTC correctly
- [ ] All existing callers audited; none silently depend on old behavior
- [ ] Tests pass
