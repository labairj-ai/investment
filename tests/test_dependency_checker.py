"""Tests for dependency_checker.py — all dependency types including fail-safe."""
import sys
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.dependency_checker import (
    _check_price, _check_thesis_version, _check_position_weight,
    _check_macro_state, _check_financial_period,
    _check_option_iv, _check_earnings_date,
    _KNOWN_DEPENDENCY_TYPES,
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


# ── OPTION_IV ────────────────────────────────────────────────────────────────

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


# ── EARNINGS_DATE ─────────────────────────────────────────────────────────────

def test_earnings_date_safe():
    far_future = (date.today() + timedelta(days=30)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": far_future}
    assert _check_earnings_date(dep, {"ANET": "2026-06-30"}) is None


def test_earnings_date_passed():
    past = (date.today() - timedelta(days=5)).isoformat()
    dep = {"dependency_key": "ANET", "original_value": past}
    reason = _check_earnings_date(dep, {})
    assert reason is not None
    assert "passed" in reason.lower()


# ── FAIL-SAFE for unknown types ───────────────────────────────────────────────

def test_unknown_dependency_types_are_not_in_known_set():
    assert "BANANA" not in _KNOWN_DEPENDENCY_TYPES
    assert "CUSTOM_SIGNAL" not in _KNOWN_DEPENDENCY_TYPES


def test_all_known_types_have_handlers():
    """Every type in _KNOWN_DEPENDENCY_TYPES must be handled in check_all_dependencies dispatch."""
    from agents import dependency_checker as dc
    import inspect
    source = inspect.getsource(dc.check_all_dependencies)
    for dtype in _KNOWN_DEPENDENCY_TYPES:
        assert f'"{dtype}"' in source or f"'{dtype}'" in source, \
            f"Dependency type {dtype!r} not handled in check_all_dependencies"
