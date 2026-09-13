# Fail Closed When Account Binding Policy Cannot Be Loaded

- **ID:** 0276
- **Status:** done
- **Created:** 2026-09-13
- **Priority:** normal
- **Depends:** 0272

## Problem

`initialize_trading_session()` wraps `load_policy()` in a bare `except Exception: expected_bid = None`, so a corrupt, missing, or unreadable policy silently disables the account binding check. For a safety feature the failure mode should be the opposite: inability to verify identity should halt the session, not skip the check. This is particularly important once a real broker adapter is configured, where a misconfiguration could route live orders to the wrong account.

## Proposed approach

- Distinguish two cases in `initialize_trading_session()`:
  1. **Policy loads successfully and `expected_broker_account_id` is None** (shadow/paper default, opt-out): skip check, proceed. This is the existing documented opt-out path.
  2. **Policy fails to load** (IOError, JSON parse error, missing file): log error, return `TradingReadyState.HALTED`. Do not silently treat as "no expected ID".
- Add a policy field or config flag (e.g. `require_account_binding: bool`) that, when true, also halts if `expected_broker_account_id` is None — for live accounts where the operator must explicitly configure the expected ID.
- Add chaos tests:
  - Policy load raises → HALTED (currently passes because exception is swallowed)
  - `require_account_binding=True` with no configured ID → HALTED
  - `require_account_binding=False` with no configured ID → TRADING_READY (existing behavior preserved)

## Touches

- `trade_engine/execution_engine.py` — `initialize_trading_session()`: split policy-load error from missing-field
- `trade_engine/policy.py` — `require_account_binding` field or equivalent
- `tests/test_chaos.py` — policy-load-failure and require_binding tests

## Done when

- [x] Policy load failure (exception) → `HALTED`; not treated as "no expected ID"
- [x] `expected_broker_account_id = None` with no `require_account_binding` → check skipped (paper/shadow compat preserved)
- [x] `require_account_binding = True` with no configured ID → `HALTED`
- [x] Chaos test: corrupt/missing policy file → HALTED
- [x] Chaos test: `require_account_binding=True`, no ID configured → HALTED
- [x] All existing 0272 account-binding tests still pass

## Outcome

`initialize_trading_session()` step 0 now has two separate try/except blocks: the first loads policy and raises on failure (→ HALTED with log error), the second checks broker account ID match as before. `policy.py` adds `require_account_binding()` method reading `circuit_breakers["require_account_binding"]`. If `require_account_binding=True` and no `expected_broker_account_id` is configured, session returns HALTED. If policy load raises any exception, session returns HALTED. Chaos tests `TestFailClosedAccountBinding` cover all three cases.
