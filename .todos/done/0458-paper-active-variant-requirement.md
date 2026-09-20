# Require Variant Row When Base Was Eligible in PAPER_ACTIVE Sweep

- **ID:** 0458
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** 0456

## Problem

`_check_paper_variant_agreement()` in `first_sweep_acceptance.py` returns `[]`
(no failures) whenever no `decision_variants` row exists, even when the sweep
phase is `PAPER_ACTIVE`. A sweep where the challenger shadow-selected a ticker
but `decision_variants` was never written therefore produces a silent PASS, which
means the entire paper-execution path can go unvalidated while the acceptance
script reports success.

## Proposed approach

Use `base_recommendation_eligible` from `learning_sweep_runs` to give absence a
concrete semantic meaning:

- `phase = PAPER_ACTIVE` AND `base_recommendation_eligible = 1`:
  a `decision_variants` row **must** exist and `challenger_episode_id` must equal
  the shadow winner. Absence of the variant row is a **FAIL** — the paper
  execution path was expected but not recorded.

- `phase = PAPER_ACTIVE` AND `base_recommendation_eligible = 0`:
  no variant is expected. Record `"variant_check": "not_expected"` in the check
  result and skip — this is a legitimate no-op, not a gap.

If `base_recommendation_eligible` is NULL or the column is absent, treat it as
eligible (fail-closed default) rather than skipping.

Add tests:
- PAPER_ACTIVE + eligible + no variant row → FAIL
- PAPER_ACTIVE + eligible + variant row present + episode matches → PASS
- PAPER_ACTIVE + eligible + variant row present + episode mismatch → FAIL
- PAPER_ACTIVE + not eligible + no variant row → `not_expected`, no failure

## Touches

- `scripts/first_sweep_acceptance.py` (`_check_paper_variant_agreement()`)
- `tests/` (new test cases for the four scenarios above)

## Done when

- [x] Missing variant row with `base_recommendation_eligible=1` is a FAIL, not a skip
- [x] `base_recommendation_eligible=0` records `not_expected` and produces no failure
- [x] NULL / absent `base_recommendation_eligible` defaults to eligible (fail-closed)
- [x] Tests cover all four cases
