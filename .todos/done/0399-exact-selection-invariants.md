# Enforce Exactly One Base and Challenger Selection Per Cohort

- **ID:** 0399
- **Status:** done
- **Created:** 2026-09-18
- **Priority:** high
- **Depends:** none

## Problem

Base top-1 selection is now correct (one row), but challenger selection still uses `would_select = 1 if ch_score == max_challenger_score`, which marks multiple rows when two candidates share the highest adjusted score. The resulting challenger pick then falls back to insertion order (`ch_rows[0]`), making the choice non-deterministic and untested. There are no DB or test-level invariants asserting that exactly one base and one challenger row are selected per model/cohort, so this class of bug can silently recur.

## Proposed approach

- Replace the tie-allowing comparison with a deterministic single-winner selection for challenger, using the same tie-break hierarchy as base: challenger_score → base_score → ticker (alphabetical).
- Set `would_select = 1` on exactly one challenger row per cohort; all others get 0.
- Add a test (and ideally a DB CHECK or query-level assertion) that `SUM(would_select) == 1` and `SUM(base_would_select) == 1` for every model/cohort combination.
- Open question: should the tie-break be enforced at write time (Python logic) or also as a DB constraint?

## Touches

- Challenger selection logic (wherever `would_select` is assigned)
- Base selection logic (verify tie-break is already applied consistently)
- Test suite for cohort evaluation / prospective metrics

## Done when

- [ ] `would_select = 1 if ch_score == max_challenger_score` pattern is removed
- [ ] Exactly one challenger row per model/cohort has `would_select = 1`
- [ ] Tie-breaking is deterministic: challenger_score → base_score → ticker
- [ ] Test asserts `SUM(would_select) == 1` per model/cohort
- [ ] Test asserts `SUM(base_would_select) == 1` per model/cohort
