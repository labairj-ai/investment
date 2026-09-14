# Capture Transport Failures in broker_api_log

- **ID:** 0321
- **Status:** done
- **Created:** 2026-09-14
- **Priority:** normal
- **Depends:** none

## Problem

`AlpacaAdapter._request()` appends a call record to `_recent_api_calls` only after a
successful HTTP response. If the request raises `requests.exceptions.RequestException`
(connection refused, DNS failure, timeout, SSL error) the exception is re-raised before
any record is created. The `broker_api_errors` scorecard count (`status >= 400`) therefore
misses transport-level failures entirely, making the error counter unreliable for alerting
and post-cycle diagnostics.

## Proposed approach

- In the `except requests.exceptions.RequestException` block inside `_request()`, append
  a record to `_recent_api_calls` **before** re-raising:
  ```python
  self._recent_api_calls.append({
      "method": method,
      "path": path,
      "status_code": None,
      "error_type": type(exc).__name__,
  })
  raise
  ```
- Update the `broker_api_errors` scorecard metric to count records where
  `status_code is None` in addition to `status_code >= 400`.
- Add a unit test: mock `session.request` to raise `requests.ConnectionError`; assert the
  call record appears in `_recent_api_calls` with `status_code=None`.

## Touches

- `trade_engine/alpaca_adapter.py` — `_request()` except block; scorecard helper
- `tests/test_alpaca_adapter.py` — new transport-error test

## Done when

- [x] `_request()` appends `{"method": ..., "path": ..., "status_code": None, "error_type": ...}` on `RequestException` before re-raising
- [x] `broker_api_errors` count includes `status_code is None` entries
- [x] Unit test: `ConnectionError` during request → record in `_recent_api_calls` with `status_code=None`
- [x] All existing tests pass

## Outcome

_request() appends {status_code: None, error_type: ...} to _recent_api_calls before re-raising on RequestException. runner.py broker_api_errors counter updated to count None entries. New test: test_transport_error_appended_to_recent_api_calls. 718 tests pass.
