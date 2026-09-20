# Make Production Cache Reuse Contract Aware

- **ID:** 0540
- **Status:** backlog
- **Created:** 2026-09-20
- **Priority:** high
- **Depends:** 0536

## Problem

`generate_holding_macro_scores(force=False)` currently treats every score younger than seven days as reusable, even when its `scorer_contract_hash` is missing or belongs to an older scorer. A contract deployment can therefore leave production consuming an old cached score while downstream coverage correctly reports it as stale.

## Proposed approach

- Compute the current scorer contract hash before loading the cache.
- Reuse a recent score only when its payload has the exact current hash.
- Send missing or mismatched scores through the normal scoring path.
- Add direct tests for stale-contract refresh and current-contract cache reuse with `force=False`.

## Touches

- `portfolio_ai.py`
- Cache lifecycle tests

## Done when

- [ ] Fresh scores with an old or missing contract hash are regenerated.
- [ ] Fresh scores with the current contract hash are reused without an LLM call.
- [ ] Regenerated scores persist the current contract and prompt hashes.
- [ ] Both cache branches are covered by tests.
