# Ledger Sub-Accounting Invariant: Assert supported + unsupported = processed

- **ID:** 0520
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** normal
- **Depends:** 0515

## Problem

0515 added `supported_scored_n` and `unsupported_n` columns to `macro_scoring_runs` and separated the LLM-scored from fund-bypass counters. However, the invariant that ties them together — `supported_scored_n + unsupported_n == scored_n` — is not asserted anywhere. If a code path increments one counter but not another, the mismatch is silent. A run could report `scored_n=10, supported_scored_n=3, unsupported_n=4` and nobody would notice the 3-item gap.

## Proposed approach

At the point in `generate_holding_macro_scores()` where the primary invariant `scored_n + failed_n == expected_n` is checked, add a second assertion:

```python
# Primary invariant (from 0515): total processed + failed = expected
if scored_n + failed_n != len(to_score):
    raise RuntimeError(f"[MacroScores] FATAL accounting mismatch: expected={len(to_score)}, scored={scored_n}, failed={failed_n}")

# Sub-accounting invariant: supported + unsupported = processed
if supported_scored_n + unsupported_n != scored_n:
    raise RuntimeError(
        f"[MacroScores] FATAL sub-accounting mismatch: "
        f"supported={supported_scored_n}, unsupported={unsupported_n}, sum={supported_scored_n+unsupported_n}, processed={scored_n}"
    )
```

Both raise and persist `status='FAILED'` before raising, following the same pattern as the primary invariant from 0515.

This invariant is cheap to check (three integers) and catches counter drift immediately at end-of-run, before the COMPLETE status is written.

## Touches

- `portfolio_ai.py` — `generate_holding_macro_scores()` only; two-line assertion after primary invariant

## Done when

- [ ] `supported_scored_n + unsupported_n == scored_n` asserted at end of scoring run
- [ ] Mismatch raises `RuntimeError` and persists `status='FAILED'` before raising
- [ ] Assertion runs after the primary invariant check (same block, same error handling)
- [ ] No change to counter increment logic — only the terminal assertion
