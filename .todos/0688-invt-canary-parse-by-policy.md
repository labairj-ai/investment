# Remove Global legacy_utc Opt-In from INV-T Canary

- **ID:** 0688
- **Status:** backlog
- **Created:** 2026-09-25
- **Priority:** high
- **Depends:** 0684, 0686

## Problem

Inside the INV-T timestamp registry loop in `scripts/canary_production_state.py`, every timestamp is parsed with `legacy_utc=True` regardless of column policy:

```python
parsed = _pts(ts_val, legacy_utc=True)
```

This disables the 0683 protection globally inside the canary. For `utc_legacy_ok` columns (e.g. `news_events.extracted_at`), a newly introduced ambiguous T-separator value like `"2026-09-25T14:30:00"` is silently accepted — `legacy_utc=True` lets it parse, and the legacy warning logic only checks for space-separated strings. A real regression produces no violation.

There is also a separate bug: the canary's internal `_parse_ts()` returns naive datetimes for Z-suffix values but aware datetimes for explicit offsets. `_V2_DEPLOY_DT` is naive, so a legitimate `"2026-09-25T00:00:00+00:00"` timestamp can eventually trigger `aware < naive` → `TypeError`.

## Proposed approach

**Parse by policy instead of globally opting in:**

- `utc_canonical` columns: call `parse_timestamp(ts_val)` with no escape hatch. Any T-separator naive string on a post-contract row raises and becomes a violation.
- `utc_legacy_ok` columns: explicitly check for the known legacy space-separator format (`" "` in the string, no `T`). If it matches the known legacy format, call `parse_timestamp(ts_val, legacy_utc=True)`. For any other format, call `parse_timestamp(ts_val)` without the escape hatch — a new T-separator naive value must fail.

**Fix `_parse_ts()` / `_V2_DEPLOY_DT`:** normalize `_parse_ts()` to always return UTC-aware datetimes (reuse `time_utils.parse_timestamp()` there), and make `_V2_DEPLOY_DT` UTC-aware. This prevents the future `aware < naive` TypeError when explicit-offset timestamps appear.

## Touches

- `scripts/canary_production_state.py` — policy-specific parsing in TIMESTAMP_REGISTRY loop; fix `_parse_ts()` / `_V2_DEPLOY_DT` aware/naive mismatch
- `tests/test_portfolio_brief.py` — add: new T-sep naive in `utc_legacy_ok` column → violation; space-sep in `utc_legacy_ok` → accepted; `utc_canonical` T-sep naive → violation; explicit-offset timestamp no TypeError

## Done when

- [ ] `utc_canonical` columns: T-separator naive string on post-contract row → violation (no `legacy_utc=True` escape)
- [ ] `utc_legacy_ok` columns: known space-sep UTC → warning/accepted; T-separator naive → violation
- [ ] `_parse_ts()` always returns UTC-aware datetimes
- [ ] `_V2_DEPLOY_DT` is UTC-aware; comparison with explicit-offset timestamps raises no TypeError
- [ ] Test: new T-sep naive in `utc_legacy_ok` column → INV-T violation
- [ ] Test: explicit-offset timestamp processed without TypeError
- [ ] All existing canary tests pass
