# Eliminate Legacy Table Read in Validated Stability Fields

- **ID:** 0525
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0517, 0519

## Problem

After the table split in 0517, `_is_formally_usable()` correctly reads from `macro_dimension_validation` using the active `acceptance_record_id`. However, the code path that populates `*_validated_stability` fields in score blobs still queries the old `macro_dimension_stability` table. This means a score blob can contain `rate_usable_for_attribution = True` (from the new gate) alongside `rate_validated_stability` drawn from a stale legacy row — the decision is right but the provenance is wrong. Six months from now that discrepancy will be miserable to diagnose when investigating why an episode was included in training data.

## Proposed approach

Create a single helper — e.g. `_accepted_dim_state(ticker, dim, conn)` — that:
1. Looks up the active `record_id` from `macro_acceptance_state` (same query as `_is_formally_usable()`)
2. Queries `macro_dimension_validation WHERE acceptance_record_id=? AND ticker=? AND dimension=?`
3. Returns a dict with `stability_class`, `mean_score`, `stddev`, `n_samples`, `record_id`, `usable` (bool)
4. Returns a safe default (all None, `usable=False`) if no active acceptance or no matching row

Replace all callsites that currently read `*_validated_stability` from `macro_dimension_stability` with this helper. Replace the `_is_formally_usable()` call in `_usable_for_attribution()` with `_accepted_dim_state(...).usable` so there is exactly one query path.

Also verify that the acceptance_record_id written into score blobs (if any) comes from the same source.

## Touches

- `portfolio_ai.py` — new `_accepted_dim_state()` helper; remove legacy `macro_dimension_stability` reads for provenance fields; update `_is_formally_usable()` / `_usable_for_attribution()` to use helper

## Done when

- [ ] `_accepted_dim_state()` helper exists and is the single source for accepted dimension state
- [ ] No production code path reads `*_validated_stability` from `macro_dimension_stability`
- [ ] `_is_formally_usable()` and the stability-field population share the same DB query path
- [ ] Score blobs whose `acceptance_record_id` is populated derive it from the same active record as the usability gate
- [ ] `macro_dimension_stability` reads remain at most for backward-compat migration logic in `_init_ai_tables()`
