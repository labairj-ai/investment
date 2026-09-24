# Version the Brief Policy

- **ID:** 0659
- **Status:** backlog
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0658

## Problem

The production canary uses a date string (`LEGACY_CUTOFF = "2026-09-24"`) to distinguish pre-fix historical rows from rows governed by the current policy. This is fragile for two reasons: (1) the deploy happened mid-day, so rows from the same date are a mix of old and new policy; (2) timestamps are stored inconsistently (`captured_at` is UTC ISO, `generated_at` is local-style), making date comparisons unreliable.

The correct long-term signal is not *when* a brief was generated but *which policy version* generated it. A persisted `brief_policy_version` field makes the canary's legacy/current classification clean and immune to timezone issues.

## Proposed approach

- Define `BRIEF_POLICY_VERSION = "v2"` as a module-level constant in `portfolio_ai.py` (increment when policy semantics change in a backward-incompatible way — e.g. when the state derivation function is changed by 0658).
- In `create_portfolio_brief()`, add `"brief_policy_version": BRIEF_POLICY_VERSION` to `briefing_output` before persisting.
- In `portfolio_brief_provenance`, `brief_policy_version` ends up inside `briefing_output_json`. No schema change needed.
- Update `scripts/canary_production_state.py`: replace the date-based `LEGACY_CUTOFF` logic with a policy-version check:
  - Rows where `briefing_output_json.brief_policy_version == CURRENT_POLICY_VERSION` → must satisfy all current invariants
  - Rows where version is absent or different → classified as `[LEGACY]`, not violations
- Remove the date-based cutoff entirely.

The canary imports `BRIEF_POLICY_VERSION` from `portfolio_ai` so the version is always in sync between the code that writes briefs and the code that validates them.

## Touches

- `portfolio_ai.py` — `BRIEF_POLICY_VERSION = "v2"` constant; `create_portfolio_brief()` writes it to output
- `scripts/canary_production_state.py` — replace date cutoff with version-based legacy classification; import `BRIEF_POLICY_VERSION`
- `tests/` — test: persisted brief output contains `brief_policy_version == "v2"`; test: canary classifies v1/absent rows as legacy and v2 rows as current

## Done when

- [ ] `BRIEF_POLICY_VERSION = "v2"` defined in `portfolio_ai.py`
- [ ] Every brief persisted by `create_portfolio_brief()` includes `"brief_policy_version": "v2"` in its output
- [ ] `scripts/canary_production_state.py` classifies rows by policy version, not by date
- [ ] Pre-v2 rows (version absent or != "v2") appear as `[LEGACY]`, not violations
- [ ] v2 rows must satisfy all current invariants
- [ ] Test: persisted brief output contains correct `brief_policy_version`
- [ ] After deploy: canary produces 0 violations (all historical rows classified as legacy)
