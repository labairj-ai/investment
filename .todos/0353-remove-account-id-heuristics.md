# Remove Account-ID String-Match Routing Heuristic

- **ID:** 0353
- **Status:** backlog
- **Created:** 2026-09-17
- **Priority:** high
- **Depends:** 0349

## Problem

`build_intent()` still falls back to `"ALPACA" in account_id.upper()` when `role` is NULL, routing that account to the challenger path. This directly violates the acceptance criterion from 0349: a future `ALPACA_LIVE_01` account with `role=NULL` would be classified as a paper challenger and execute a different ticker than the accepted recommendation on what could be a live account. Missing/unknown role should default to safe behavior (champion/non-autonomous), not infer behavior from the account ID string.

## Proposed approach

- Remove the `or (acct_role is None and "ALPACA" in account_id.upper())` branch entirely from `build_intent()`
- Routing rule becomes: `is_paper_challenger = (acct_role == "paper_challenger")` — no fallback
- Any account without an explicit `role='paper_challenger'` gets champion behavior
- Ensure `AGENTIC_ALPACA_01` has `role='paper_challenger'` in the seed (already done in 0349); verify in migration
- Add a warning log when `role` is NULL so operators know to set it explicitly

## Touches

- `trade_engine/intent_builder.py` — remove string-match fallback; single-condition role check
- `tests/test_calibration.py` or `tests/test_trade_engine.py` — test `ALPACA_LIVE_01` with `role=NULL` → champion; test `FOO_ALPACA_TEST` with `role=NULL` → champion; test `AGENTIC_ALPACA_01` with `role='paper_challenger'` → challenger

## Done when

- [ ] `build_intent()` routes solely by `trading_accounts.role = 'paper_challenger'`; no string-match fallback
- [ ] An account with `role=NULL` (including any account with "ALPACA" in its ID) receives champion behavior
- [ ] Test: `ALPACA_LIVE_01` role=NULL → symbol = champion ticker
- [ ] Test: `FOO_ALPACA_TEST` role=NULL → symbol = champion ticker
- [ ] Test: `AGENTIC_ALPACA_01` role='paper_challenger' → symbol = challenger ticker
- [ ] `python -m pytest tests/` passes with no regressions
