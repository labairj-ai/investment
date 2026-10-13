# Fail-Closed Policy Version Classification

- **ID:** 0663
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0659

## Problem

The current version classification has a subtle hole: anything other than "v2" becomes legacy. If a persistence regression causes a newly generated brief to omit `brief_policy_version`, the canary says "legacy row — warning" instead of "missing required field — violation." A failure of the versioning mechanism itself silently opts a bad row out of current-policy validation.

The contract needs three explicit states:

| Version field | Classification |
|---|---|
| Known historical (v1, absent on pre-v2 rows) | `LEGACY` — warning |
| Current (`"v2"`) | `CURRENT` — validate |
| Missing on a post-v2 record | `VIOLATION` |
| Unknown future string (e.g. `"v3"`) | `VIOLATION` or explicit fail |

## Proposed approach

**Short-term (code-only):**
- Define `KNOWN_LEGACY_VERSIONS = {None, "v1"}` in the canary. Any row whose version is in this set → legacy warning.
- Any row with an unrecognized version that isn't `BRIEF_POLICY_VERSION` → violation.
- To distinguish "pre-v2 historical missing version" from "post-v2 broken missing version": compare `captured_at` to the date `BRIEF_POLICY_VERSION = "v2"` was first deployed (2026-09-24T19:26 UTC). Rows before this timestamp with missing version → legacy. Rows after this timestamp with missing version → violation. This is a one-time bridge; when v3 ships, its deploy timestamp becomes its own boundary.

**Longer-term (schema change, optional for this todo):**
- Add `policy_version TEXT NOT NULL DEFAULT 'legacy-v1'` column to `portfolio_brief_provenance`.
- Backfill the 33 existing rows to `legacy-v1`.
- Make `create_portfolio_brief()` write the column directly alongside the JSON blob.
- Canary reads `policy_version` column rather than parsing it out of `briefing_output_json`.
- `NULL` in this column = `NOT NULL` constraint violation at write time — the DB enforces it.

Either approach is acceptable. The short-term code-only fix resolves the safety gap immediately.

## Touches

- `scripts/canary_production_state.py` — three-state classification; `KNOWN_LEGACY_VERSIONS` set; timestamp bridge for missing-version records
- `portfolio_ai.py` — if schema change: write `policy_version` column in `create_portfolio_brief()`
- DB migration (if schema change) — backfill existing 33 rows; add NOT NULL constraint
- `tests/` — test each of the three classification outcomes; missing version on old record → legacy; missing version on new record → violation

## Done when

- [x] Missing `brief_policy_version` on a post-v2 record is classified as a violation, not a legacy warning
- [x] Known pre-v2 historical records (absent version, captured before v2 deploy) still classified as legacy
- [x] Unknown version string (neither a known legacy nor current) → violation
- [x] Tests for all three classification states
- [ ] After deploy: 0 new violations on v2 rows; 33 legacy warnings unchanged

## Outcome

Replaced `_is_legacy(briefing_output)` with `_row_classification(briefing_output, captured_at)` returning "CURRENT", "LEGACY", or "UNKNOWN_VERSION". Added `KNOWN_LEGACY_VERSIONS = {None, "v1"}` and `V2_DEPLOY_TIMESTAMP = "2026-09-24T19:26:00"`. Added INV-9 sweep: any UNKNOWN_VERSION row is flagged as a violation. INV-1, 2, 3, 8 updated to use the new classification. The ai_insights invariant (INV-3) uses `generated_at` as the timestamp for classification. Four new tests: current-passes, legacy-is-warning, missing-version-new-record-is-violation, unknown-version-is-violation. Chose code-only approach (no schema migration) per the short-term path in the todo.
