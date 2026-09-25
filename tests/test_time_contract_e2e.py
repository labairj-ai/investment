"""End-to-end timestamp contract acceptance test (0680).

Verifies UTC identity is preserved through serialization and Eastern
display is correct across EST, EDT, and DST transitions.
"""
import time
from datetime import datetime

import pytest

from time_utils import (
    TZ_UTC, TZ_EASTERN,
    now_utc, now_utc_iso, epoch_to_utc,
    parse_timestamp, to_eastern, format_eastern,
)


def test_utc_round_trip():
    """UTC identity preserved through Z-suffix ISO serialization."""
    original = now_utc()
    serialized = original.strftime("%Y-%m-%dT%H:%M:%SZ")
    recovered = parse_timestamp(serialized)
    assert abs((original - recovered).total_seconds()) < 1


def test_eastern_est():
    """Eastern rendering correct in EST (January — UTC-5)."""
    utc = datetime(2026, 1, 15, 15, 0, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 10
    assert "EST" in format_eastern(utc)


def test_eastern_edt():
    """Eastern rendering correct in EDT (July — UTC-4)."""
    utc = datetime(2026, 7, 15, 15, 0, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 11
    assert "EDT" in format_eastern(utc)


def test_calendar_date_around_utc_midnight():
    """2026-09-25 02:30 UTC renders as Sep 24 in Eastern (EDT)."""
    utc = datetime(2026, 9, 25, 2, 30, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.day == 24
    assert et.month == 9
    assert et.year == 2026


def test_spring_forward():
    """2026-03-08 07:00 UTC = 03:00 AM EDT (02:00 AM does not exist)."""
    utc = datetime(2026, 3, 8, 7, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 3
    assert "EDT" in format_eastern(utc)
    # Spring-forward: 2 AM doesn't exist; 7:00 UTC is 3:00 AM EDT
    assert et.utcoffset().total_seconds() == -4 * 3600


def test_fall_back_post_transition():
    """2026-11-01 06:00 UTC = 01:00 AM EST (after fall-back at 02:00 AM)."""
    utc = datetime(2026, 11, 1, 6, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 1
    assert "EST" in format_eastern(utc)
    # Round-trip: UTC identity preserved
    recovered = et.astimezone(TZ_UTC)
    assert abs((utc - recovered).total_seconds()) < 1


def test_fall_back_pre_transition():
    """2026-11-01 05:00 UTC = 01:00 AM EDT (before fall-back)."""
    utc = datetime(2026, 11, 1, 5, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 1
    assert "EDT" in format_eastern(utc)


def test_epoch_to_utc_matches_direct():
    """epoch_to_utc is equivalent to datetime.fromtimestamp(tz=UTC)."""
    ts = time.time()
    from_epoch = epoch_to_utc(ts)
    direct = datetime.fromtimestamp(ts, tz=TZ_UTC)
    assert abs((from_epoch - direct).total_seconds()) < 0.01


def test_utc_eastern_utc_round_trip():
    """UTC → Eastern → UTC preserves the original instant."""
    utc = datetime(2026, 7, 15, 20, 30, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    back = et.astimezone(TZ_UTC)
    assert abs((utc - back).total_seconds()) < 1


def test_legacy_parse_preserves_instant():
    """Legacy space-sep string parses as UTC and round-trips correctly."""
    original = datetime(2026, 9, 24, 20, 0, 0, tzinfo=TZ_UTC)
    legacy_str = "2026-09-24 20:00:00"
    parsed = parse_timestamp(legacy_str)
    assert abs((original - parsed).total_seconds()) < 1
