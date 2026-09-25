# Eliminate Business-Date Regressions from date.today()

- **ID:** 0685
- **Status:** backlog
- **Created:** 2026-09-25
- **Priority:** high
- **Depends:** 0682

## Problem

0682 replaced all 17 `date.today()` calls in `serve.py`, but the same class of bug still exists outside it. In `create_portfolio_brief()` (`portfolio_ai.py`):

```python
today = date.today().isoformat()
```

This determines the `ai_insights.day` key. Near UTC midnight, it can disagree with the Eastern business date — e.g. 00:30 UTC is still the prior calendar day in New York. If the newsletter runs at that time, the `ai_insights` row gets keyed to tomorrow's date from New York's perspective.

Additionally, the CI guard currently blocks `datetime.now()` without tz but does NOT block `date.today()` or `datetime.date.today()` — exactly the regression class 0682 was meant to fix. Without this guard, the bug can be silently reintroduced in any file.

## Proposed approach

**Fix the production call:**
In `portfolio_ai.py` `create_portfolio_brief()`, replace:
```python
today = date.today().isoformat()
```
with:
```python
from time_utils import today_eastern
today = today_eastern().isoformat()
```

**Extend CI guard** (`tests/test_ci_datetime_guard.py`):
- Add a regex pattern to `PROHIBITED` that catches `date.today()` and `datetime.date.today()` in production code. Exclude `time_utils.py`, `tests/`, `scripts/`, `migrations/`, `venv/` per existing convention.
- Add a positive failure test: `test_guard_catches_date_today()`.
- Add an integration test that scans `portfolio_ai.py` specifically and asserts zero violations.

**Audit remaining files** for any other `date.today()` / `datetime.date.today()` calls not covered by 0682.

## Touches

- `portfolio_ai.py` — fix `create_portfolio_brief()` business-date key
- `tests/test_ci_datetime_guard.py` — add `date.today()` to `PROHIBITED`; positive failure test; portfolio_ai integration test

## Done when

- [ ] `create_portfolio_brief()` uses `today_eastern()` for the `ai_insights.day` key
- [ ] CI guard catches `date.today()` and `datetime.date.today()` in production code
- [ ] Positive failure test: `test_guard_catches_date_today()` passes
- [ ] Integration test: `portfolio_ai.py` has zero `date.today()` violations
- [ ] All existing tests pass
