# Fix book_mtm CI Regression in yfinance Mocks

- **ID:** 0575
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** none

## Problem

The implementation switched from `yf.download(...)` to `yf.Ticker(ticker).history(...)` but the tests in `tests/test_book_mtm_prices.py` still monkeypatch `yfinance.download`. As a result the mock is never hit, the tests call the real network provider, and receive live prices instead of the expected invalid/empty values. This causes 5 failures on current main (commit f2f83a6) with 1,438 passing and 18 skipped. The failures are unrelated to fill/reconciliation work from 0572–0574.

## Proposed approach

- Update `tests/test_book_mtm_prices.py` to patch `yfinance.Ticker` (or `yfinance.Ticker.history`) instead of `yfinance.download`.
- Preferred alternative: extract the historical-price fetch into a small injectable provider function so unit tests pass a stub and network access can never leak regardless of which yfinance API is used in future.
- Verify no other test files still reference the old `yfinance.download` patch for MTM paths.

## Touches

- `tests/test_book_mtm_prices.py`
- Possibly the module under test that calls `yf.Ticker(ticker).history(...)` if a provider-injection approach is taken.

## Done when

- [x] All 5 previously failing tests in `tests/test_book_mtm_prices.py` pass without network access
- [x] `pytest` on main returns green (1,440+ passing, no new failures)
- [x] No test in the suite calls the real yfinance network provider

## Outcome

Updated `tests/test_book_mtm_prices.py`: replaced `monkeypatch.setattr(yfinance, 'download', ...)` with `MockTicker` / `WrongDateTicker` / `BrokenTicker` classes patching `yfinance.Ticker`. Tests now validate the actual `Ticker().history()` call path including `start`, `end`, and `auto_adjust` args. Full suite: 1445 passed, 0 failed, 16 skipped.
