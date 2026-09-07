# Add CC-Assignment Lifecycle Test and Verify Transaction Rollback Coverage

- **ID:** 0117
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0113

## Problem

The stale lifecycle TRIM test (expected `(1-f)*hold_r`) was already fixed in the 0103 implementation. Failure-injection rollback tests exist in `test_agent_db.py` (0104). What is still missing is an end-to-end lifecycle test for the CC assignment path added in 0113: verifying that when `evaluate_matured_recommendations` processes a SELL_CC that expires assigned, the `30d_post` outcome row carries the locked assignment return rather than 0.0. Without this test, a future regression in `evaluate_matured_recommendations`'s cc_assignment_state block (which had a `h_price` NameError, now fixed) would not be caught.

## Proposed approach

Add to `tests/test_lifecycle.py`:
1. **CC assignment end-to-end**: create a SELL_CC recommendation in the in-memory DB (accepted, with exec_rec for premium + strike), seed `holding_day` prices (entry, at_expiry > strike, 30d_post), seed `spy_prices`. Call `evaluate_matured_recommendations()`. Assert: `at_expiry` row has `cc_assignment_state='assigned'`; `30d_post` row has `actual_r == (K - entry + premium) / entry` (not 0.0).
2. **CC expired path**: same setup but S_exp < K. Assert `cc_assignment_state='expired'`; `30d_post` actual_r uses uncapped stock formula.

## Touches

- `tests/test_lifecycle.py`

## Done when

- [ ] CC assigned end-to-end test passes (30d_post returns locked assignment return)
- [ ] CC expired end-to-end test passes (30d_post returns uncapped stock + premium formula)
- [ ] Tests use the in-memory `mem_db` fixture (no real DB or network calls)
