# Legacy Timestamp Compatibility

- **ID:** 0677
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0669

## Problem

Historical records use a mix of formats (`"2026-09-24T23:49:21Z"`, `"2026-09-24 23:49:21"`, etc.) and cannot be mass-rewritten. The new `parse_timestamp()` utility must handle these formats correctly without silently inferring server-local time for naive strings.

## Proposed approach

Enumerate all known legacy timestamp formats in the production DB (audit `portfolio_brief_provenance.captured_at`, `ai_insights.generated_at`, and any other timestamped tables). Document each as either:
- Confirmed UTC (e.g. fields written with `utcfromtimestamp()`)
- Known local-time (document what timezone)
- Unknown/ambiguous (flag and handle conservatively)

In `parse_timestamp()`, define an explicit compatibility path for each known legacy format — documented in code, not inferred. Unknown formats must fail visibly rather than silently assuming server-local time. Do not mass-update historical rows.

## Touches

- `time_utils.py` — `parse_timestamp()` compatibility paths (from 0669)
- `tests/` — tests for each known legacy format; unknown format raises

## Done when

- [x] Existing records are not mass-updated
- [x] Known historical formats parse successfully
- [x] Legacy UTC-naive fields are explicitly identified and documented
- [x] Compatibility assumptions have tests
- [x] Unknown timestamp formats fail visibly rather than silently assuming server-local time
## Outcome

Implemented as part of 0668-0680 batch commit.
