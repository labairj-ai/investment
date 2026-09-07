# Require Action-Specific Execution Fields; Derive Position Size Server-Side

- **ID:** 0107
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** none

## Problem

`execution_validation.py` checks each field only when it is present (`if quantity is not None: ...`), so a SELL_CC body omitting `contracts`, `strike`, `premium`, and `expiration` passes validation. Similarly, EXIT and TRIM can omit `quantity` or `execution_price` without triggering a 400. Additionally, `position_shares_before` is trusted from the client body, which means the coverage check (`contracts × 100 ≤ position_shares_before`) is only as reliable as whatever number the client sends. The canonical share count should come from the server-side portfolio loader.

## Proposed approach

- In `execution_validation.py`, define per-action required-field sets:
  - `EXIT / TRIM`: `execution_date`, `quantity`, `execution_price` required; `position_shares_before` forbidden from client.
  - `SELL_CC`: `execution_date`, `contracts`, `strike`, `premium`, `expiration` required; `position_shares_before` forbidden from client.
  - `ROLL_*`: `execution_date`, `btc_price` (or `execution_price`), `sto_premium` (or `premium`), `new_strike` (or `strike`), `new_expiration` (or `expiration`) required.
  - `BUY_TO_CLOSE`: `execution_date`, `execution_price` (btc cost) required.
  - `ALLOW_ASSIGNMENT`: `execution_date` required; `execution_price` optional (defaults to strike from open cc_position).
- In `serve.py` execute endpoint: load `position_shares_before` from `load_positions()` (canonical CSV loader) before calling `validate_execution_body()`; pass it in as a server-side value so the validator can enforce coverage without trusting the client.
- If the ticker is not found in `load_positions()`, return 422 with a clear message rather than skipping the coverage check.
- Remove `position_shares_before` from the documented request body for these actions (or ignore it if supplied).

## Touches

- `execution_validation.py` — required-field enforcement per action type
- `serve.py` — load canonical position before validation; pass server-side `pos_before` to validator
- `portfolio_positions.py` — verify `load_positions()` is importable from serve context without circular deps
- `tests/test_execute_validation.py` — add scenarios for missing required fields per action type
- `tests/test_lifecycle.py` — update any lifecycle test that passes `position_shares_before` in the client body

## Done when

- [ ] POST SELL_CC with missing `contracts` → 400 with a message naming the missing field.
- [ ] POST SELL_CC with missing `strike` → 400.
- [ ] POST SELL_CC with missing `premium` → 400.
- [ ] POST SELL_CC with missing `expiration` → 400.
- [ ] POST EXIT with missing `quantity` → 400.
- [ ] POST EXIT with missing `execution_price` → 400.
- [ ] POST TRIM with missing `quantity` → 400.
- [ ] `position_shares_before` from client body is ignored; server loads it from `load_positions()`; coverage check uses the canonical value.
- [ ] POST SELL_CC for a ticker not in `holdings.csv` → 422.
- [ ] All new validation scenarios covered by unit tests in `test_execute_validation.py`.
- [ ] Full pytest suite passes.
- [ ] Manual test on the live dashboard: attempt a SELL_CC execution with a blank `contracts` field; confirm the UI surfaces the 400 error.
