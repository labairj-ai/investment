# Finish Timestamp Registry with Typed Policies and Monotonicity

- **ID:** 0689
- **Status:** backlog
- **Created:** 2026-09-25
- **Priority:** normal
- **Depends:** 0688

## Problem

The TIMESTAMP_REGISTRY in `scripts/canary_production_state.py` covers four text-timestamp columns, but the 0684 design also called out `recommendations` and `decision_episodes`. Those tables store timestamps as `REAL` epoch-seconds values, not text strings — so `parse_timestamp()` cannot be applied directly. The registry has no mechanism to handle epoch-numeric columns and no chronological consistency check.

## Proposed approach

**Evolve the registry to understand storage types.** Add a `storage_type` field alongside `policy`:

- `utc_iso` — Z-suffix or explicit-offset text; use `parse_timestamp(ts_val)` (strict)
- `utc_space_legacy` — space-sep text; explicit known-legacy check before parsing
- `epoch_seconds` — REAL column; validate with `epoch_to_utc(float(ts_val))`, check non-negative and not unreasonably far in future
- `required_id` — must be non-null/non-empty (no timestamp validation)

**Seed new entries:**
- `recommendations`: `created_at` (`epoch_seconds`)
- `decision_episodes`: `captured_at` (`epoch_seconds`)

**Add optional monotonicity check:** for registry entries with `monotonic=True`, verify timestamps do not decrease across rows ordered by the id column. Failing rows produce an `[INV-T mono]` violation.

**Lower-priority follow-on:** migrate `ai_insights.generated_at` new writes to `now_utc_iso()` (Z-suffix) so `utc_space_legacy` becomes purely historical rather than an actively produced format.

## Touches

- `scripts/canary_production_state.py` — extend TIMESTAMP_REGISTRY with `storage_type`; epoch-seconds validation; optional monotonicity check; add `recommendations` and `decision_episodes` entries
- `tests/test_portfolio_brief.py` — epoch validation tests (negative → violation, far-future → violation, valid → pass); monotonicity violation test

## Done when

- [ ] TIMESTAMP_REGISTRY entries include a `storage_type` field understood by the sweep loop
- [ ] Epoch-seconds columns validated with `epoch_to_utc()`: negative or impossibly-future value → violation
- [ ] `recommendations.created_at` and `decision_episodes.captured_at` covered by INV-T
- [ ] Optional monotonicity check implemented; backward timestamp in a `monotonic=True` column → `[INV-T mono]` violation
- [ ] Tests for epoch validation and monotonicity
- [ ] All existing canary tests pass
