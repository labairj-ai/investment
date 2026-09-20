# Make NULL Paper Eligibility Fail Closed End-to-End

- **ID:** 0460
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** none

## Problem

`_find_paper_sweep()` queries only rows where `base_recommendation_eligible = 1`, so a completed `PAPER_ACTIVE` sweep with `NULL` eligibility is silently invisible to the runner. The runner reports "No completed base-eligible PAPER_ACTIVE sweep found yet" — an "it's too early" signal — instead of failing closed on malformed evidence. `_check_paper_variant_agreement()` already contains correct NULL fail-closed logic, but it is never reached because the sweep is filtered out before the helper is called.

## Proposed approach

- Change `_find_paper_sweep()` (or a new wrapper) to select completed `PAPER_ACTIVE` sweeps regardless of `base_recommendation_eligible` value, then classify results:
  - `eligible = 1` → qualifying sweep, proceed normally
  - `eligible = 0` → not yet qualifying, return NO_SWEEP (exit 2)
  - `eligible = NULL` → malformed evidence, fail acceptance (exit 1 or 3)
- The three-way split keeps the "too early" path correct while making NULL an explicit integrity failure rather than an invisible non-result.
- Add a test that exercises the full `run_paper_acceptance()` path with a seeded `PAPER_ACTIVE` sweep whose `base_recommendation_eligible` is NULL and asserts acceptance fails (not "too early").

## Touches

- `Desktop/investment/` — paper acceptance runner / sweep locator (exact filename unknown)
- `Desktop/investment/tests/` — new end-to-end test for NULL eligibility path

## Done when

- [ ] A completed `PAPER_ACTIVE` sweep with `base_recommendation_eligible = NULL` causes acceptance to fail, not return NO_SWEEP
- [ ] `run_paper_acceptance()` end-to-end test covers the NULL eligibility case
- [ ] Existing qualifying (`eligible=1`) and not-yet-qualifying (`eligible=0`) paths are unaffected
