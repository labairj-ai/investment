# Harden Alpaca Paper Isolation

- **ID:** 0291
- **Status:** backlog
- **Created:** 2026-09-13
- **Priority:** high
- **Depends:** none

## Problem

The current `AlpacaAdapter` paper guard checks `if "paper" not in base_url: raise`, which prevents the obvious live URL but is not an allowlist. A URL like `https://something-paper.example.com` passes the guard. Alpaca's documented paper trading endpoint is exactly `https://paper-api.alpaca.markets`; the live endpoint is `api.alpaca.markets`. These use separate credentials and separate domains. The current guard does not enforce the correct hostname, does not enforce HTTPS, and does not prevent a look-alike domain from passing inspection. Additionally, `initialize_trading_session()` verifies account-ID binding for generic adapters, but the Alpaca adapter does not yet enforce this at construction time, meaning a misconfigured account ID would only be discovered at the first trading session — after credentials have already been used.

## Proposed approach

- Replace the substring check in `AlpacaAdapter.__init__()` with a parsed URL allowlist:
  - Parse `base_url` with `urllib.parse.urlparse`.
  - Assert `scheme == "https"`.
  - Assert `hostname == "paper-api.alpaca.markets"` (exact match, no substrings).
  - Raise `ValueError` with a descriptive message listing the required hostname on any mismatch.
- Remove the ability to override the trading host to an arbitrary URL in the production constructor. If a test-only escape hatch is needed, gate it behind an explicit `_allow_custom_url=True` parameter that is never set in production code.
- Prohibit `paper=False` unconditionally (already done in 0287 — confirm preserved).
- Add account-ID binding at construction: accept an optional `expected_account_id` parameter; if provided, verify it matches the value returned by `get_account_id()` at session init.
- Tests:
  - `paper=True` + exact paper hostname → constructs ok
  - `paper=True` + live hostname → raises
  - `paper=True` + look-alike hostname (`something-paper.example.com`) → raises
  - `paper=True` + HTTP (not HTTPS) → raises
  - `paper=False` → raises
  - `expected_account_id` mismatch at session init → raises / HALTED

## Touches

- `trade_engine/alpaca_adapter.py` — constructor URL parsing, account-ID binding
- `tests/test_chaos.py` or `tests/test_trade_engine.py` — expanded paper-guard tests

## Done when

- [ ] `AlpacaAdapter` parses `base_url` and enforces `scheme=https` and `hostname=paper-api.alpaca.markets` exactly (no substring)
- [ ] Look-alike domains (e.g. `something-paper.example.com`) fail at construction
- [ ] HTTP URLs fail at construction
- [ ] `paper=False` still raises unconditionally
- [ ] `expected_account_id` mismatch is detected and raises / causes HALTED at session init
- [ ] All existing 612 tests still pass
