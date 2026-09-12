"""Tests for canonical IRS LT/ST calendar utilities (0165)."""
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tax_utils import lt_threshold, is_long_term, days_until_lt


# ── lt_threshold ──────────────────────────────────────────────────────────────

def test_normal_jan_1():
    """Jan 1 purchase → LT starts Jan 2 of next year (not Jan 1)."""
    assert lt_threshold(date(2024, 1, 1)) == date(2025, 1, 2)


def test_normal_mid_year():
    """Jul 15 purchase → LT starts Jul 16 next year."""
    assert lt_threshold(date(2024, 7, 15)) == date(2025, 7, 16)


def test_feb_28():
    """Feb 28 purchase → LT starts Mar 1 next year (Feb 28 + 1 = Mar 1 in non-leap 2025)."""
    assert lt_threshold(date(2024, 2, 28)) == date(2025, 3, 1)


def test_feb_29_leap_year():
    """Feb 29 purchase (leap year) → LT starts Mar 1 next year (no Feb 29 in 2025)."""
    assert lt_threshold(date(2024, 2, 29)) == date(2025, 3, 1)


def test_dec_31():
    """Dec 31 purchase → LT starts Jan 1 two years later."""
    assert lt_threshold(date(2024, 12, 31)) == date(2026, 1, 1)


# ── is_long_term ──────────────────────────────────────────────────────────────

def test_exact_anniversary_is_still_st():
    """Disposed exactly one year after purchase is ST — holding period not yet > 1 year."""
    # purchase Jan 1 2024; anniversary Jan 1 2025 is still ST
    assert is_long_term(date(2024, 1, 1), date(2025, 1, 1)) is False


def test_one_day_past_anniversary_is_lt():
    """Disposed one day after the anniversary is LT."""
    assert is_long_term(date(2024, 1, 1), date(2025, 1, 2)) is True


def test_feb_29_lot_lt_on_mar_1():
    """Feb-29 lot is LT on Mar 1 next year."""
    assert is_long_term(date(2024, 2, 29), date(2025, 3, 1)) is True


def test_feb_29_lot_st_on_feb_28_next_year():
    """Feb-29 lot is still ST on Feb 28 next year."""
    assert is_long_term(date(2024, 2, 29), date(2025, 2, 28)) is False


def test_clearly_lt():
    """Lot held two years is obviously LT."""
    assert is_long_term(date(2022, 6, 1), date(2024, 6, 1)) is True


def test_clearly_st():
    """Lot held six months is obviously ST."""
    assert is_long_term(date(2024, 1, 1), date(2024, 7, 1)) is False


# ── days_until_lt ─────────────────────────────────────────────────────────────

def test_days_until_lt_future():
    """30 days before LT threshold → returns 30."""
    purchase = date(2024, 1, 1)
    # threshold = 2025-01-02; as_of = 2024-12-03 → 30 days out
    as_of = date(2024, 12, 3)
    assert days_until_lt(purchase, as_of) == 30


def test_days_until_lt_on_threshold_day():
    """On the exact threshold day → returns 0."""
    purchase = date(2024, 1, 1)
    as_of = date(2025, 1, 2)
    assert days_until_lt(purchase, as_of) == 0


def test_days_until_lt_already_lt():
    """After threshold → returns negative."""
    purchase = date(2024, 1, 1)
    as_of = date(2025, 6, 1)
    assert days_until_lt(purchase, as_of) < 0
