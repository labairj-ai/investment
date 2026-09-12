"""Canonical IRS tax-lot calendar utilities (0165).

The IRS "more than one year" holding-period rule starts the day after
acquisition. A share bought on Jan 1 becomes long-term on Jan 2 of the
following year — not Jan 1. Fixed timedelta(days=365) arithmetic is wrong
around leap years and exact anniversary dates.
"""
from datetime import date, timedelta


def lt_threshold(purchase_date: date) -> date:
    """First date on which a lot purchased on purchase_date qualifies as long-term.

    Holding period starts the day after acquisition; LT = held MORE than one year.
      purchase 2024-01-01 → LT from 2025-01-02
      purchase 2024-02-29 → LT from 2025-03-01  (Feb-29 leap-year guard)
    """
    try:
        return purchase_date.replace(year=purchase_date.year + 1) + timedelta(days=1)
    except ValueError:  # Feb 29 in a non-leap target year → Mar 1
        return date(purchase_date.year + 1, 3, 1)


def is_long_term(purchase_date: date, disposal_date: date) -> bool:
    """True if a lot purchased on purchase_date is long-term by disposal_date."""
    return disposal_date >= lt_threshold(purchase_date)


def days_until_lt(purchase_date: date, as_of: date) -> int:
    """Days until the lot becomes long-term. Negative if already long-term."""
    return (lt_threshold(purchase_date) - as_of).days
