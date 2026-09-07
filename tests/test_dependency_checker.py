"""Tests for dependency_checker.py — all dependency types including fail-safe."""
import sys
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.dependency_checker import (
    _check_price, _check_thesis_version, _check_position_weight,
    _check_macro_state, _check_financial_period,
    _check_option_iv, _check_option_expiration, _check_earnings_date,
    _check_event_calendar, _check_option_liquidity, _check_estimate_revision,
    _check_cc_position_state, _check_option_mark, _KNOWN_DEPENDENCY_TYPES,
)


# ── PRICE ────────────────────────────────────────────────────────────────────

def test_price_within_tolerance():
    dep = {"dependency_key": "ANET", "original_value": "100.00", "tolerance": 0.05}
    assert _check_price(dep, {"ANET": 103.0}) is None


def test_price_outside_tolerance():
    dep = {"dependency_key": "ANET", "original_value": "100.00", "tolerance": 0.02}
    reason = _check_price(dep, {"ANET": 103.5})
    assert reason is not None
    assert "3.5" in reason or "3" in reason


# ── THESIS_VERSION ───────────────────────────────────────────────────────────

def test_thesis_version_unchanged():
    dep = {"dependency_key": "ANET", "original_value": "2"}
    assert _check_thesis_version(dep, {"ANET": 2}) is None


def test_thesis_version_changed():
    dep = {"dependency_key": "ANET", "original_value": "2"}
    reason = _check_thesis_version(dep, {"ANET": 3})
    assert reason is not None
    assert "v2" in reason and "v3" in reason


# ── POSITION_WEIGHT ──────────────────────────────────────────────────────────

def test_weight_within_tolerance():
    dep = {"dependency_key": "ANET", "original_value": "10.0", "tolerance": 2.0}
    assert _check_position_weight(dep, {"ANET": 11.5}) is None


def test_weight_outside_tolerance():
    dep = {"dependency_key": "ANET", "original_value": "10.0", "tolerance": 2.0}
    reason = _check_position_weight(dep, {"ANET": 13.5})
    assert reason is not None


# ── MACRO_STATE ──────────────────────────────────────────────────────────────

import json

def test_macro_state_stable():
    orig = json.dumps({"rate_sensitivity": 50, "inflation_hedge": 60})
    dep = {"dependency_key": "ANET", "original_value": orig, "tolerance": 15.0}
    current = {"ANET": {"rate_sensitivity": 55, "inflation_hedge": 63}}
    assert _check_macro_state(dep, current) is None


def test_macro_state_changed_20pts():
    orig = json.dumps({"rate_sensitivity": 50})
    dep = {"dependency_key": "ANET", "original_value": orig, "tolerance": 15.0}
    current = {"ANET": {"rate_sensitivity": 71}}  # 21-point shift
    reason = _check_macro_state(dep, current)
    assert reason is not None
    assert "Macro" in reason


# ── FINANCIAL_PERIOD ─────────────────────────────────────────────────────────

def test_financial_period_no_new_data():
    dep = {"dependency_key": "ANET", "original_value": "2026-06-30"}
    assert _check_financial_period(dep, {"ANET": "2026-06-30"}) is None


def test_financial_period_new_quarter():
    dep = {"dependency_key": "ANET", "original_value": "2026-06-30"}
    reason = _check_financial_period(dep, {"ANET": "2026-09-30"})
    assert reason is not None
    assert "2026-09-30" in reason


# ── OPTION_IV (backwards compat alias → expiration check) ────────────────────

def test_option_iv_not_expired():
    future = (date.today() + timedelta(days=30)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": future}
    assert _check_option_iv(dep, None) is None


def test_option_iv_expired():
    past = (date.today() - timedelta(days=1)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": past}
    reason = _check_option_iv(dep, None)
    assert reason is not None
    assert "expired" in reason.lower()


def test_option_iv_expiring_soon():
    soon = (date.today() + timedelta(days=2)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": soon}
    reason = _check_option_iv(dep, None)
    assert reason is not None  # 2 days left → supersede


# ── OPTION_EXPIRATION (renamed from OPTION_IV) ────────────────────────────────

def test_option_expiration_not_expired():
    future = (date.today() + timedelta(days=14)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": future}
    assert _check_option_expiration(dep, None) is None


def test_option_expiration_expired():
    past = (date.today() - timedelta(days=1)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": past}
    reason = _check_option_expiration(dep, None)
    assert reason is not None
    assert "expired" in reason.lower()


# ── OPTION_LIQUIDITY stub ─────────────────────────────────────────────────────

def test_option_liquidity_stub_returns_none():
    """Without option_quote_snapshots data, stub returns None (no supersession)."""
    dep = {"dependency_key": "ANET", "threshold": 0.15}
    # Patch get_latest_option_snapshot to return None (no data)
    from unittest.mock import patch
    import agent_db
    with patch.object(agent_db, "get_latest_option_snapshot", return_value=None):
        result = _check_option_liquidity(dep, None)
    assert result is None


# ── ESTIMATE_REVISION stub ────────────────────────────────────────────────────

def test_estimate_revision_stub_returns_none(mem_db):
    """Without estimate_history data, stub returns None (no supersession)."""
    dep = {"dependency_key": "ANET", "original_value": "5.00", "threshold": 0.10}
    result = _check_estimate_revision(dep, None)
    assert result is None


# ── EVENT_CALENDAR stub ───────────────────────────────────────────────────────

def test_event_calendar_stub_returns_none(mem_db):
    """Without event_calendar data, stub returns None (no supersession)."""
    dep = {"dependency_key": "ANET", "event_type": "earnings"}
    result = _check_event_calendar(dep, None)
    assert result is None


# ── EARNINGS_DATE ─────────────────────────────────────────────────────────────

def test_earnings_date_safe():
    far_future = (date.today() + timedelta(days=30)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": far_future}
    from unittest.mock import patch
    import agent_db
    with patch.object(agent_db, "get_latest_earnings_date", return_value=None):
        assert _check_earnings_date(dep, {"ANET": "2026-06-30"}) is None


def test_earnings_date_passed():
    past = (date.today() - timedelta(days=5)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": past}
    from unittest.mock import patch
    import agent_db
    with patch.object(agent_db, "get_latest_earnings_date", return_value=None):
        reason = _check_earnings_date(dep, {})
    assert reason is not None
    assert "passed" in reason.lower()


def test_earnings_date_authoritative_supersedes(mem_db):
    """0075: seeded earnings_dates row supersedes when date is imminent."""
    import agent_db
    imminent = (date.today() + timedelta(days=3)).isoformat()
    agent_db.upsert_earnings_date("ANET", imminent, confirmed_by="yfinance", confidence="provider_estimated")
    dep = {"dependency_key": "ANET", "original_value": (date.today() + timedelta(days=60)).isoformat()}
    reason = _check_earnings_date(dep, {})
    assert reason is not None
    assert "imminent" in reason.lower()


def test_earnings_date_fallback_to_heuristic(mem_db):
    """0075: when no earnings_dates row, falls back to heuristic original_value."""
    far_future = (date.today() + timedelta(days=60)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": far_future}
    # No earnings_dates seeded — get_latest_earnings_date returns None
    result = _check_earnings_date(dep, {})
    assert result is None  # 60 days out, no supersession


# ── FAIL-SAFE for unknown types ───────────────────────────────────────────────

def test_unknown_dependency_types_are_not_in_known_set():
    assert "BANANA" not in _KNOWN_DEPENDENCY_TYPES
    assert "CUSTOM_SIGNAL" not in _KNOWN_DEPENDENCY_TYPES


def test_option_expiration_in_known_dependency_types():
    assert "OPTION_EXPIRATION" in _KNOWN_DEPENDENCY_TYPES


def test_all_known_types_have_handlers():
    """Every type in _KNOWN_DEPENDENCY_TYPES must be handled in check_all_dependencies dispatch."""
    from agents import dependency_checker as dc
    import inspect
    source = inspect.getsource(dc.check_all_dependencies)
    for dtype in _KNOWN_DEPENDENCY_TYPES:
        assert f'"{dtype}"' in source or f"'{dtype}'" in source, \
            f"Dependency type {dtype!r} not handled in check_all_dependencies"


# ── 0090: CC_POSITION_STATE ───────────────────────────────────────────────────

def test_cc_position_state_no_change_returns_none(monkeypatch):
    """No supersession when CC position state is unchanged."""
    import agent_db as _adb
    monkeypatch.setattr(_adb, "get_open_cc_for_ticker", lambda ticker: None)
    dep = {"dependency_key": "ANET", "original_value": "none"}
    assert _check_cc_position_state(dep, None) is None


def test_cc_position_state_opened_triggers_supersession(monkeypatch):
    """Supersede when a CC was opened after rec was made (original=none, now=open)."""
    import agent_db as _adb
    monkeypatch.setattr(_adb, "get_open_cc_for_ticker",
                        lambda ticker: {"id": 1, "ticker": "ANET", "status": "open"})
    dep = {"dependency_key": "ANET", "original_value": "none"}
    result = _check_cc_position_state(dep, None)
    assert result is not None
    assert "state changed" in result.lower()


def test_cc_position_state_closed_triggers_supersession(monkeypatch):
    """Supersede when the CC was open at rec time but is now closed."""
    import agent_db as _adb
    monkeypatch.setattr(_adb, "get_open_cc_for_ticker", lambda ticker: None)
    dep = {"dependency_key": "ANET", "original_value": "open"}
    result = _check_cc_position_state(dep, None)
    assert result is not None


def test_cc_position_state_in_known_types():
    """CC_POSITION_STATE must be in _KNOWN_DEPENDENCY_TYPES."""
    assert "CC_POSITION_STATE" in _KNOWN_DEPENDENCY_TYPES


# ── 0096: ESTIMATE_REVISION type + period filtering ──────────────────────────

def test_estimate_revision_filters_by_type_and_period(mem_db):
    """FY2027 EPS dep is NOT superseded when a different estimate type changes (0096)."""
    import agent_db
    # Seed a FY2027 EPS estimate at $8.50
    agent_db.append_estimate_history("ANET", "FY2027", "EPS", 8.50)
    # Seed a different estimate (Q3 Revenue) that has changed a lot
    agent_db.append_estimate_history("ANET", "Q3", "REVENUE", 1_000_000.0)
    agent_db.append_estimate_history("ANET", "Q3", "REVENUE", 800_000.0)  # 20% drop

    # Dependency based on FY2027 EPS — should NOT be superseded by Q3 revenue change
    dep = {
        "dependency_key": "ANET",
        "original_value": "8.50",
        "threshold": 0.10,
        "estimate_type": "EPS",
        "period": "FY2027",
    }
    result = _check_estimate_revision(dep, None)
    assert result is None, (
        f"FY2027 EPS dep incorrectly superseded by Q3/REVENUE change: {result}"
    )


def test_estimate_revision_triggers_on_correct_type_and_period(mem_db):
    """FY2027 EPS dep IS superseded when FY2027 EPS itself moves > threshold (0096)."""
    import agent_db
    agent_db.append_estimate_history("ANET", "FY2027", "EPS", 8.50)
    agent_db.append_estimate_history("ANET", "FY2027", "EPS", 9.50)  # ~11.7% up

    dep = {
        "dependency_key": "ANET",
        "original_value": "8.50",
        "threshold": 0.10,
        "estimate_type": "EPS",
        "period": "FY2027",
    }
    result = _check_estimate_revision(dep, None)
    assert result is not None
    assert "EPS/FY2027" in result


def test_estimate_revision_legacy_fallback_no_crash(mem_db):
    """Legacy dep without estimate_type/period falls back gracefully (no exception)."""
    import agent_db
    agent_db.append_estimate_history("ANET", "FY2026", "EPS", 7.00)

    dep = {
        "dependency_key": "ANET",
        "original_value": "7.00",
        "threshold": 0.10,
        # No estimate_type or period — legacy format
    }
    # Should not raise; returns None (estimate unchanged) or a reason if moved > threshold
    result = _check_estimate_revision(dep, None)
    # The latest row is FY2026/EPS at 7.00 — no change → None
    assert result is None


# ── 0095: OPTION_MARK dependency handler ─────────────────────────────────────

def test_option_mark_no_data_returns_none(monkeypatch):
    """Without option_quote_snapshots data, returns None (no supersession)."""
    import agent_db
    monkeypatch.setattr(agent_db, "get_latest_option_snapshot", lambda *a, **kw: None)
    dep = {"dependency_key": "ANET", "original_value": "3.00", "tolerance": 0.20}
    assert _check_option_mark(dep, None) is None


def test_option_mark_within_tolerance(monkeypatch):
    """Mark moved 15% (within 20% threshold) → no supersession."""
    import agent_db
    monkeypatch.setattr(agent_db, "get_latest_option_snapshot",
                        lambda *a, **kw: {"bid": 3.30, "ask": 3.50, "iv": 0.45})
    dep = {"dependency_key": "ANET", "original_value": "3.00", "tolerance": 0.20}
    # mid = (3.30+3.50)/2 = 3.40 → 13.3% move < 20%
    assert _check_option_mark(dep, None) is None


def test_option_mark_outside_tolerance(monkeypatch):
    """Mark moved 25% (> 20% threshold) → supersede."""
    import agent_db
    monkeypatch.setattr(agent_db, "get_latest_option_snapshot",
                        lambda *a, **kw: {"bid": 3.65, "ask": 3.85, "iv": 0.55})
    dep = {"dependency_key": "ANET", "original_value": "3.00", "tolerance": 0.20}
    # mid = (3.65+3.85)/2 = 3.75 → 25% move > 20%
    result = _check_option_mark(dep, None)
    assert result is not None
    assert "25%" in result or "mark" in result.lower()


def test_option_mark_in_known_dependency_types():
    """OPTION_MARK must be in _KNOWN_DEPENDENCY_TYPES and handled in dispatch."""
    assert "OPTION_MARK" in _KNOWN_DEPENDENCY_TYPES
