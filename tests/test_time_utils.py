"""Tests for time_utils canonical timestamp contract (0668/0669/0677)."""
import pytest
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from time_utils import (
    TZ_UTC, TZ_EASTERN,
    now_utc, now_utc_iso, now_utc_space, epoch_to_utc,
    parse_timestamp, to_eastern, format_eastern, today_eastern,
)


# ── Basic constructors ────────────────────────────────────────────────────────

def test_now_utc_is_aware():
    dt = now_utc()
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_now_utc_iso_ends_with_z():
    s = now_utc_iso()
    assert s.endswith("Z")
    assert "T" in s


def test_now_utc_space_format():
    s = now_utc_space()
    # "2026-09-24 20:00:00" — 19 chars, space separator
    assert len(s) == 19
    assert " " in s


def test_epoch_to_utc_roundtrip():
    import time
    ts = time.time()
    dt = epoch_to_utc(ts)
    assert dt.tzinfo is not None
    assert abs(dt.timestamp() - ts) < 0.01


# ── parse_timestamp ───────────────────────────────────────────────────────────

def test_parse_z_suffix():
    dt = parse_timestamp("2026-09-24T23:49:21Z")
    assert dt.tzinfo == TZ_UTC
    assert dt.year == 2026 and dt.month == 9 and dt.day == 24
    assert dt.hour == 23


def test_parse_explicit_utc_offset():
    dt = parse_timestamp("2026-09-24T23:49:21+00:00")
    assert dt.utcoffset().total_seconds() == 0


def test_parse_explicit_negative_offset():
    # -04:00 = EDT; should convert to UTC
    dt = parse_timestamp("2026-09-24T19:49:21-04:00")
    assert dt.utcoffset().total_seconds() == 0
    assert dt.hour == 23  # 19 + 4 = 23 UTC


def test_parse_space_sep_naive_legacy():
    # Legacy ai_insights format — confirmed UTC (0677 contract)
    dt = parse_timestamp("2026-09-24 20:00:00")
    assert dt.tzinfo == TZ_UTC
    assert dt.hour == 20


def test_parse_bare_datetime_naive_raises():
    """Naive datetime object without tzinfo is rejected by default (0686)."""
    naive = datetime(2026, 9, 24, 20, 0, 0)
    with pytest.raises(ValueError, match="naive datetime object rejected"):
        parse_timestamp(naive)


def test_parse_aware_datetime_converts_to_utc():
    eastern = ZoneInfo("America/New_York")
    aware = datetime(2026, 9, 24, 20, 0, 0, tzinfo=eastern)
    dt = parse_timestamp(aware)
    assert dt.utcoffset().total_seconds() == 0
    assert dt.hour == 0  # 20:00 EDT = 00:00 UTC next day
    assert dt.day == 25


def test_parse_unknown_format_raises():
    with pytest.raises(ValueError, match="unrecognized format"):
        parse_timestamp("not-a-date")


def test_parse_empty_raises():
    with pytest.raises(ValueError):
        parse_timestamp("")


def test_parse_none_raises():
    with pytest.raises(ValueError):
        parse_timestamp(None)


# ── 0677 Legacy compatibility ─────────────────────────────────────────────────

def test_legacy_space_sep_is_utc():
    dt = parse_timestamp("2026-09-24 20:00:00")
    assert dt.tzinfo == TZ_UTC
    assert dt.hour == 20


def test_legacy_z_suffix():
    dt = parse_timestamp("2026-09-24T23:49:21Z")
    assert dt.utcoffset().total_seconds() == 0
    assert dt.hour == 23


# ── to_eastern ────────────────────────────────────────────────────────────────

def test_to_eastern_raises_on_naive():
    with pytest.raises(ValueError, match="timezone-aware"):
        to_eastern(datetime(2026, 9, 24, 20, 0))


def test_to_eastern_est_january():
    utc = datetime(2026, 1, 15, 15, 0, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 10  # UTC-5 in winter
    assert et.utcoffset().total_seconds() == -5 * 3600


def test_to_eastern_edt_july():
    utc = datetime(2026, 7, 15, 15, 0, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 11  # UTC-4 in summer
    assert et.utcoffset().total_seconds() == -4 * 3600


# ── format_eastern ────────────────────────────────────────────────────────────

def test_format_eastern_contains_est_in_winter():
    utc = datetime(2026, 1, 15, 15, 0, 0, tzinfo=TZ_UTC)
    s = format_eastern(utc)
    assert "EST" in s


def test_format_eastern_contains_edt_in_summer():
    utc = datetime(2026, 7, 15, 15, 0, 0, tzinfo=TZ_UTC)
    s = format_eastern(utc)
    assert "EDT" in s


# ── DST transitions ───────────────────────────────────────────────────────────

def test_spring_forward_2026():
    # 2026-03-08 07:00 UTC = 3:00 AM EDT (2 AM → 3 AM spring forward)
    utc = datetime(2026, 3, 8, 7, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 3
    assert "EDT" in format_eastern(utc)


def test_fall_back_2026_after_transition():
    # 2026-11-01 06:00 UTC = 1:00 AM EST (after fall-back at 2:00 AM)
    utc = datetime(2026, 11, 1, 6, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 1
    assert "EST" in format_eastern(utc)
    # Round-trip identity
    recovered = et.astimezone(TZ_UTC)
    assert abs((utc - recovered).total_seconds()) < 1


def test_fall_back_2026_before_transition():
    # 2026-11-01 05:00 UTC = 1:00 AM EDT (before fall-back)
    utc = datetime(2026, 11, 1, 5, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.hour == 1
    assert "EDT" in format_eastern(utc)


# ── Calendar date boundary ────────────────────────────────────────────────────

def test_utc_midnight_date_in_eastern():
    # 2026-09-25 02:30 UTC = 2026-09-24 22:30 EDT
    utc = datetime(2026, 9, 25, 2, 30, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    assert et.day == 24
    assert et.month == 9


# ── Round-trip ────────────────────────────────────────────────────────────────

def test_utc_round_trip_via_iso():
    original = now_utc()
    serialized = original.strftime("%Y-%m-%dT%H:%M:%SZ")
    recovered = parse_timestamp(serialized)
    assert abs((original - recovered).total_seconds()) < 1


def test_eastern_to_utc_round_trip():
    utc = datetime(2026, 7, 15, 15, 0, 0, tzinfo=TZ_UTC)
    et = to_eastern(utc)
    back = et.astimezone(TZ_UTC)
    assert abs((utc - back).total_seconds()) < 1


# ── 0686: naive datetime object rejection ─────────────────────────────────────

def test_parse_naive_datetime_legacy_utc_opt_in():
    """Naive datetime with legacy_utc=True is promoted to UTC (0686)."""
    naive = datetime(2026, 9, 24, 20, 0, 0)
    dt = parse_timestamp(naive, legacy_utc=True)
    assert dt.tzinfo == TZ_UTC
    assert dt.hour == 20


def test_parse_aware_datetime_still_converts():
    """Aware datetime still converts to UTC regardless of legacy_utc flag (0686)."""
    eastern = ZoneInfo("America/New_York")
    aware = datetime(2026, 9, 24, 20, 0, 0, tzinfo=eastern)
    dt = parse_timestamp(aware)
    assert dt.utcoffset().total_seconds() == 0
    assert dt.day == 25  # 20:00 EDT = 00:00 UTC next day


# ── 0683: parse_timestamp tightened ───────────────────────────────────────────

def test_parse_t_sep_naive_raises():
    """Canonical T-separator without Z or offset is now rejected (0683)."""
    with pytest.raises(ValueError, match="naive T-separator"):
        parse_timestamp("2026-09-25T14:30:00")


def test_parse_t_sep_naive_legacy_utc_opt_in():
    """legacy_utc=True allows T-separator naive strings with explicit justification."""
    # legacy_utc=True: caller documents this is a known UTC value
    dt = parse_timestamp("2026-09-25T14:30:00", legacy_utc=True)
    assert dt.tzinfo == TZ_UTC
    assert dt.hour == 14
    assert dt.minute == 30


def test_parse_space_sep_still_works_after_tighten():
    """Space-sep legacy format still parses without legacy_utc flag (0683)."""
    dt = parse_timestamp("2026-09-24 20:00:00")
    assert dt.tzinfo == TZ_UTC
    assert dt.hour == 20


def test_parse_z_suffix_still_works_after_tighten():
    """Z-suffix canonical format unaffected by tightening (0683)."""
    dt = parse_timestamp("2026-09-25T14:30:00Z")
    assert dt.tzinfo == TZ_UTC
    assert dt.hour == 14


# ── 0682: today_eastern() ─────────────────────────────────────────────────────

def test_today_eastern_returns_date_object():
    """today_eastern() returns a date in America/New_York."""
    import datetime as _dt
    d = today_eastern()
    assert isinstance(d, _dt.date)
    # Result must equal now_utc() converted to Eastern
    expected = now_utc().astimezone(TZ_EASTERN).date()
    assert d == expected


def test_today_eastern_is_consistent_with_now_eastern():
    """today_eastern() and now_eastern().date() agree."""
    from time_utils import now_eastern
    assert today_eastern() == now_eastern().date()
