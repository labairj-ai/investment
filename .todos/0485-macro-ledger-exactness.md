# Make Macro Ledger Truly Fail-Closed

- **ID:** 0485
- **Status:** done
- **Created:** 2026-09-19
- **Priority:** high
- **Depends:** 0478

## Problem

Three edge cases remain after 0478. First, the STARTED row write is gated on `if DB_PATH.exists()` — if the database doesn't exist yet, scoring proceeds without any ledger record. Second, the final UPDATE retries twice but does not raise on exhaustion, so the function can return results with a permanently un-finalised ledger row. Third, tickers omitted from the LLM response are added to `run_errors` but `failed_n` is not incremented, breaking the invariant `expected_n == scored_n + failed_n`.

## Proposed approach

- Remove the `DB_PATH.exists()` guard — the ledger write should create the DB if absent (sqlite3 does this automatically); raise if the INSERT fails for any reason.
- After both UPDATE retry attempts fail, raise rather than logging and returning — a run with an un-finalised ledger is not a valid completed run.
- When a response omits an expected ticker, increment `failed_n` and add to `errors_json` in the same branch that adds to `run_errors`.
- Assert `expected_n == scored_n + failed_n` before the final UPDATE; log a loud warning if it doesn't hold (indicates a bug in the counting logic).

## Touches

- `portfolio_ai.py` — `generate_holding_macro_scores()` ledger lifecycle

## Done when

- [ ] Scoring with a non-existent DB still writes a STARTED row (sqlite3 creates the file)
- [ ] Final UPDATE failure after two retries raises instead of returning silently
- [ ] Omitted tickers increment `failed_n`
- [ ] `expected_n == scored_n + failed_n` assertion fires before final UPDATE
