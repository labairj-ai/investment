# Broaden Timestamp Contract Canary

- **ID:** 0684
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0678, 0683

## Problem

INV-T currently checks only `portfolio_brief_provenance.captured_at` and `ai_insights.generated_at`, only the 50 newest rows, and only whether timestamps can be parsed. It does not verify UTC canonical format, check required-field presence, detect impossible future timestamps, check chronological ordering, or sweep the other high-risk persistence tables identified in 0670.

"0 production violations" currently means the two sampled columns in the two checked tables parsed without error — not that the full timestamp contract is clean across the application.

## Proposed approach

Define a `TIMESTAMP_REGISTRY` dict mapping table → list of `(column, policy)` where `policy` is one of:
- `"utc_canonical"` — must be Z-suffix or space-sep UTC; newer rows must have Z-suffix
- `"utc_legacy_ok"` — space-sep accepted (documented legacy)
- `"required"` — must be non-null/non-empty

Seed the registry with high-risk tables from 0670:
- `portfolio_brief_provenance`: `captured_at` (utc_canonical), `brief_id` (required)
- `ai_insights`: `generated_at` (utc_legacy_ok for pre-0667, utc_canonical after)
- `portfolio_brief_snapshots`: `captured_at` (utc_canonical)
- `recommendations`: timestamp column (utc_canonical)
- `decision_episodes`: timestamp column (utc_canonical)
- `news_events`: timestamp column (utc_canonical)

For each registered field:
- Parse with `parse_timestamp()` — any failure = violation
- For `utc_canonical`: verify no arbitrary naive T-separator strings in post-contract rows
- Check required fields are non-null
- Check timestamp is not more than 5 minutes in the future (clock-skew tolerance)
- Check chronological ordering on the most recent N rows (no timestamp goes backward)

Do not try to cover every table at once. Sweep all rows for each registered field (not just the latest 50). Expand the registry as new persistence tables are introduced.

The canary remains read-only, never rewrites data. Output includes table, row ID, field, and the offending value.

## Touches

- `scripts/canary_production_state.py` — replace narrow INV-T with `TIMESTAMP_REGISTRY`-driven sweep
- `tests/` — test: missing required field → violation; future timestamp → violation; parseable legacy → warning; unparseable → violation

## Done when

- [x] `TIMESTAMP_REGISTRY` defined with documented policy per column
- [x] All rows swept (not just latest 50) for registered fields
- [x] Unparseable timestamp → violation with table/row/field/value in output
- [x] Impossible future timestamp → violation
- [x] Required-field missing → violation
- [x] Known legacy format (space-sep UTC) → warning, not violation
- [x] Tests for each check type
- [x] Production canary clean after deploy
