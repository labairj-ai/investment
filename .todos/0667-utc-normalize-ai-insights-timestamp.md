# UTC-Normalize ai_insights.generated_at

- **ID:** 0667
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0666

## Problem

`ai_insights.generated_at` is produced with `datetime.now().strftime(...)` — host-local, timezone-naive time. INV-9b compares it directly against the UTC `V2_DEPLOY_TIMESTAMP`. If the optiplex host runs in a non-UTC timezone, a post-v2 `ai_insights` write whose local time falls before the UTC cutover boundary is classified as LEGACY instead of triggering a violation — exactly the failure mode INV-9b exists to prevent.

`portfolio_brief_provenance.captured_at` is already explicitly UTC (`utcfromtimestamp(...).strftime(...)`), so INV-9 is sound. INV-9b is not because it shares the same cutover boundary but reads a local-time field.

## Proposed approach

In `portfolio_ai.py`, find where `ai_insights.generated_at` is written and change to UTC:

```python
from datetime import datetime, timezone
now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
```

Or, if `create_portfolio_brief()` already holds a UTC timestamp (from `captured_at`), derive `generated_at` from that same value rather than making a second `datetime.now()` call.

Add a comment at the `ai_insights` INSERT site and in `scripts/canary_production_state.py` documenting the DB timestamp contract:
```
# DB timestamp contract:
# portfolio_brief_provenance.captured_at  = UTC
# portfolio_brief_snapshots.captured_at   = UTC
# ai_insights.generated_at                = UTC
```

Add two tests:
- Post-cutover UTC `ai_insights` row with missing version → INV-9b violation
- Pre-cutover UTC `ai_insights` row with missing version → legacy (no violation)

## Touches

- `portfolio_ai.py` — change `datetime.now()` to `datetime.now(timezone.utc)` at the `ai_insights` write site
- `scripts/canary_production_state.py` — add DB timestamp contract comment
- `tests/test_portfolio_brief.py` — two new INV-9b UTC boundary tests

## Done when

- [x] `ai_insights.generated_at` is written as UTC (not host-local time)
- [x] DB timestamp contract documented at the write site and in the canary
- [x] Test: post-cutover UTC `generated_at` + missing version → INV-9b violation
- [x] Test: pre-cutover UTC `generated_at` + missing version → legacy
- [ ] All tests pass; production canary clean after deploy

## Outcome

Changed `_dt2.now()` to `_dt2.now(_tz2.utc)` in `create_portfolio_brief()` (portfolio_ai.py line 3203); added `timezone as _tz2` to the local import. Added DB timestamp contract comment at the INSERT site. Added matching contract comment block in canary near `V2_DEPLOY_TIMESTAMP`. Added two new tests: `test_canary_inv9b_post_cutover_utc_missing_version_is_violation` and `test_canary_inv9b_pre_cutover_utc_missing_version_is_legacy`, both derive timestamps from `V2_DEPLOY_TIMESTAMP ± 1s`. 1678 tests passing (+2).
