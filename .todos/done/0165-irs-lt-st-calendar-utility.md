# Add Canonical IRS LT/ST Calendar Utility

- **ID:** 0165
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

Five files compute long-term capital-gains status using `timedelta(days=365)`, which is wrong around leap years and anniversary dates. The IRS "more than one year" rule starts the holding period the day after acquisition, so a share bought on Jan 1 becomes LT on Jan 2 of the following year — not Jan 1. Using a fixed 365-day delta can misclassify lots near the boundary and cause incorrect tax-friction calculations in the CC assignment engine, the tax agent, and the trigger system.

## Proposed approach

Create `tax_utils.py` at the project root with three public functions:

```python
def lt_threshold(purchase_date: date) -> date:
    """First date on which a lot purchased on purchase_date qualifies as long-term."""
    try:
        return purchase_date.replace(year=purchase_date.year + 1) + timedelta(days=1)
    except ValueError:  # Feb 29 purchase in non-leap target year → Mar 1
        return date(purchase_date.year + 1, 3, 1)

def is_long_term(purchase_date: date, disposal_date: date) -> bool:
    return disposal_date >= lt_threshold(purchase_date)

def days_until_lt(purchase_date: date, as_of: date) -> int:
    """Days until lot becomes LT. Negative if already LT."""
    return (lt_threshold(purchase_date) - as_of).days
```

Add `tests/test_tax_utils.py` covering:
- Normal case: Jan 1 → Jan 2 next year
- Feb 28 purchase → Mar 1 next year
- Feb 29 leap-year purchase → Mar 1 next year
- Exact anniversary is still ST; anniversary + 1 day is LT
- `days_until_lt` returns negative when already LT

## Touches

- `tax_utils.py` (new)
- `tests/test_tax_utils.py` (new)

## Done when

- [ ] `tax_utils.py` exists with all three functions, no external dependencies
- [ ] `lt_threshold(date(2024, 1, 1))` == `date(2025, 1, 2)`
- [ ] `lt_threshold(date(2024, 2, 29))` == `date(2025, 3, 1)`
- [ ] `is_long_term(date(2024, 1, 1), date(2025, 1, 1))` is `False`
- [ ] `is_long_term(date(2024, 1, 1), date(2025, 1, 2))` is `True`
- [ ] All unit tests pass
