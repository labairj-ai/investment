"""
Canonical timestamp contract for the investment platform.

Storage:    All persisted timestamps are UTC.
Display:    All human-facing timestamps render in America/New_York (DST-aware).
Market:     All market schedule logic uses America/New_York.
Learning:   All duration/cohort math operates on UTC-aware datetimes.

Prohibited in new production code (CI guard enforces):
  datetime.now()          — use now_utc()
  datetime.utcnow()       — use now_utc()
  utcfromtimestamp()      — use epoch_to_utc()
  fixed -05:00/-04:00     — use TZ_EASTERN with ZoneInfo
  string timestamp cmp    — parse first with parse_timestamp()
  "EST" / "EDT" hardcoded — use format_eastern() for abbreviation

Historical records are NOT rewritten. parse_timestamp() accepts known legacy
formats via explicit compatibility paths (see comments below).

DB timestamp contract:
  portfolio_brief_provenance.captured_at  = UTC  (Z-suffix ISO)
  portfolio_brief_snapshots.captured_at   = UTC  (Z-suffix ISO)
  ai_insights.generated_at               = UTC  (space-sep, pre-0667: UTC host confirmed)
  All other new writes use now_utc_iso()  = UTC  (Z-suffix ISO)
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

TZ_UTC = timezone.utc
TZ_EASTERN = ZoneInfo("America/New_York")

# Known legacy timestamp formats (historical records are NOT rewritten):
#   "2026-09-24T23:49:21Z"   — UTC, Z-suffix (portfolio_brief_provenance.captured_at)
#   "2026-09-24 23:49:21"    — UTC, space-sep, no suffix (ai_insights.generated_at pre-0667;
#                              confirmed written on UTC host via utcfromtimestamp/utcnow)
#   ISO with explicit offset  — treated as-is, converted to UTC


def now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware datetime."""
    return datetime.now(TZ_UTC)


def now_utc_iso() -> str:
    """Return the current UTC time as a Z-suffix ISO-8601 string."""
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc_space() -> str:
    """Return the current UTC time in space-separated format (legacy DB compat)."""
    return now_utc().strftime("%Y-%m-%d %H:%M:%S")


def epoch_to_utc(ts: float) -> datetime:
    """Convert a Unix epoch timestamp to a timezone-aware UTC datetime."""
    return datetime.fromtimestamp(ts, tz=TZ_UTC)


def parse_timestamp(s) -> datetime:
    """
    Return a timezone-aware UTC datetime from a persisted timestamp string.

    Accepts:
      - datetime objects (naive assumed UTC per legacy contract; aware converted to UTC)
      - "2026-09-24T23:49:21Z"         (Z-suffix ISO — canonical UTC)
      - "2026-09-24 23:49:21"          (space-sep naive — legacy UTC, see DB contract above)
      - "2026-09-24T23:49:21+00:00"    (explicit offset)
      - "2026-09-24T19:49:21-04:00"    (explicit offset, any zone)

    Raises ValueError for unrecognized formats rather than silently assuming local time.
    """
    if isinstance(s, datetime):
        if s.tzinfo is None:
            # Legacy naive datetimes from this codebase were written as UTC
            return s.replace(tzinfo=TZ_UTC)
        return s.astimezone(TZ_UTC)
    if not isinstance(s, str) or not s:
        raise ValueError(f"parse_timestamp: cannot parse {s!r}")
    s = s.strip()
    # Z-suffix canonical form
    if s.endswith("Z"):
        return datetime.fromisoformat(s[:-1]).replace(tzinfo=TZ_UTC)
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            return dt.astimezone(TZ_UTC)
        # Naive string — legacy UTC (space-sep format from pre-contract writes)
        return dt.replace(tzinfo=TZ_UTC)
    except ValueError:
        raise ValueError(f"parse_timestamp: unrecognized format {s!r}")


def to_eastern(dt: datetime) -> datetime:
    """
    Convert a timezone-aware datetime to America/New_York (DST-aware).
    Raises ValueError for naive inputs — do not silently assume a timezone.
    """
    if dt.tzinfo is None:
        raise ValueError("to_eastern requires a timezone-aware datetime; "
                         "use parse_timestamp() first for string inputs")
    return dt.astimezone(TZ_EASTERN)


def format_eastern(dt: datetime, fmt: str = "%b %d, %Y · %I:%M %p %Z") -> str:
    """
    Return dt formatted in America/New_York with correct EST/EDT abbreviation.
    Collapses leading space for single-digit days (e.g. "Sep  4" → "Sep 4").
    """
    et = to_eastern(dt)
    return et.strftime(fmt).replace("  ", " ")


def format_eastern_short(dt: datetime) -> str:
    """Dense table format: '09/24/26 8:42 PM EDT'"""
    et = to_eastern(dt)
    return et.strftime("%m/%d/%y %-I:%M %p %Z")
