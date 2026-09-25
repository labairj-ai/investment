# Fix v2 Cutover Boundary and Extend INV-9 to ai_insights

- **ID:** 0666
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0663

## Problem

`V2_DEPLOY_TIMESTAMP = "2026-09-24T19:26:00"` in the canary is wrong. That time came from the 0653 deployment, not from v2. Commit 17cd1bb (which first introduced `BRIEF_POLICY_VERSION = "v2"`) is timestamped 2026-09-24T23:49:21Z, so any record captured between 19:26Z and 23:49Z lacks `brief_policy_version` for a legitimate reason — v2 didn't exist yet. With the current boundary, those records are classified `UNKNOWN_VERSION` and trigger INV-9 violations instead of being labeled legacy.

Additionally, INV-9 only sweeps `portfolio_brief_provenance`. An `ai_insights` row with `portfolio_state="STABLE"` and `brief_policy_version="v99"` does not independently trigger a version violation. Because both tables are written atomically this isn't a current safety hole, but the canary's stated invariant ("any unknown-version row is a violation") isn't literally true of `ai_insights`.

## Proposed approach

**Cutover boundary:**
- Query production `portfolio_brief_provenance` for the earliest row where `json_extract(briefing_output_json, '$.brief_policy_version') = "v2"`. Use that `captured_at` as `V2_DEPLOY_TIMESTAMP` — it is the actual first moment a v2 brief was successfully persisted, which is more reliable than any deploy-log timestamp.
- Parse timestamps as `datetime` objects (not lexicographic string comparison) when classifying rows in `_row_classification()`. Both `captured_at` (from `portfolio_brief_provenance`) and `generated_at` (from `ai_insights`) use UTC ISO format; parse with `datetime.fromisoformat()`.
- Test boundary cases: one second before cutover → LEGACY; exactly at cutover → CURRENT (if version == "v2"); one second after cutover with missing version → VIOLATION.

**INV-9b (ai_insights):**
- Add a parallel sweep over `ai_insights` using the same `_row_classification(output, generated_at)` logic.
- Any `ai_insights` row classified `UNKNOWN_VERSION` → INV-9b violation.
- Use `generated_at` as the timestamp for `ai_insights` rows (analogous to `captured_at` for provenance rows).

**After fixing:**
- Deploy to optiplex.
- Run production canary. Acceptance target: 0 v2 violations; historical rows (before the corrected cutover) remain legacy; no false INV-9 or INV-9b fires.

## Touches

- `scripts/canary_production_state.py` — correct `V2_DEPLOY_TIMESTAMP`; switch to `datetime` comparison; add INV-9b sweep over `ai_insights`
- `tests/` — boundary tests at −1s / 0s / +1s relative to corrected cutover; INV-9b test for `ai_insights` unknown-version row

## Done when

- [x] `V2_DEPLOY_TIMESTAMP` is set to the actual first v2 production brief timestamp (queried from `portfolio_brief_provenance`)
- [x] Timestamp comparison uses `datetime` objects, not lexicographic string comparison
- [x] Boundary tests pass: one second before cutover → LEGACY; one second after with missing version → VIOLATION
- [x] INV-9b sweeps `ai_insights` for unknown-version rows using the same `_row_classification()` logic
- [x] INV-9b test: `ai_insights` row with `brief_policy_version="v99"` → violation
- [ ] After deploy: production canary reports 0 v2/INV-9/INV-9b violations; historical rows remain legacy warnings

## Outcome

Queried optiplex production DB: no v2 rows exist yet (optiplex was at 17cd1bb, which added `BRIEF_POLICY_VERSION` but hadn't been triggered to generate a brief with it). All 11 existing rows have `captured_at` before `2026-09-24T23:49:21` (commit timestamp of 17cd1bb). Set `V2_DEPLOY_TIMESTAMP = "2026-09-24T23:49:21"` — the first moment v2 code existed in production. This correctly classifies all 11 historical rows as LEGACY.

Added `_parse_ts()` helper and `_V2_DEPLOY_DT` module constant. `_row_classification()` now uses `ts < _V2_DEPLOY_DT` datetime comparison instead of lexicographic string comparison; handles both T and space separators and Z suffix.

Added INV-9b after INV-9: sweeps `ai_insights` with the same `_row_classification(insight, generated_at)` logic. Six new tests: boundary at -1s (no INV-9 violation), exactly at cutover (violation), +1s (violation), INV-9b unknown version, INV-9b missing post-deploy, INV-9b pre-v2 legacy no violation. 1676 tests pass.
