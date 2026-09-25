# Tighten CI EST/EDT Guard for Single Quotes and Line Numbers

- **ID:** 0687
- **Status:** backlog
- **Created:** 2026-09-25
- **Priority:** normal
- **Depends:** 0681

## Problem

The EST/EDT guard pattern only catches double-quoted strings:

```python
_EST_EDT_PATTERN = re.compile(r'(?<![#\'"a-zA-Z])("EST"|"EDT")')
```

Single-quoted variants slip through undetected:
```python
pytz.timezone('EST')
label = 'EDT'
```

The positive failure tests also use double quotes, so they don't catch the gap. There is also a diagnostic bug in `test_no_est_edt_timezone_strings`: `text.find(line_text)` always finds the *first* occurrence of an identical line in the file, so repeated matching lines report the wrong line number. Detection still works; only the reported location is wrong.

## Proposed approach

**Fix the pattern** to recognize both quote styles:
```python
_EST_EDT_PATTERN = re.compile(r'''(?<![#\'"a-zA-Z])(?:"EST"|'EST'|"EDT"|'EDT')''')
```

**Fix line-number reporting** in `test_no_est_edt_timezone_strings`: replace `text.find(line_text)` with `enumerate(text.splitlines(), start=1)` to get accurate per-line numbers.

**Add positive failure tests** for single-quoted variants:
- `pytz.timezone('EST')` → caught
- `label = 'EDT'` → caught

## Touches

- `tests/test_ci_datetime_guard.py` — update `_EST_EDT_PATTERN`; fix line-number reporting; add single-quote positive tests

## Done when

- [ ] `'EST'` and `'EDT'` single-quoted strings caught by the guard
- [ ] `"EST"` and `"EDT"` double-quoted strings still caught
- [ ] Positive failure tests for both quote styles pass
- [ ] Line-number reporting uses `enumerate(splitlines())` — no first-match false reports
- [ ] Comment-exclusion test still passes
- [ ] All existing CI guard tests pass
