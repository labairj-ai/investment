"""Tests for _validate_execution_body (serve.py, 0092)."""
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from execution_validation import validate_execution_body as _validate_execution_body

TODAY = date(2026, 9, 6)

def _rec(action="TRIM", status="accepted", created_days_ago=5):
    created_at = time.time() - created_days_ago * 86400
    return {"action": action, "status": status, "created_at": created_at, "ticker": "ANET"}


# --- date validation ---

def test_missing_execution_date_returns_400():
    err = _validate_execution_body("TRIM", {}, _rec(), TODAY)
    assert err == (400, "execution_date is required")


def test_invalid_date_format_returns_400():
    err = _validate_execution_body("TRIM", {"execution_date": "09/06/2026"}, _rec(), TODAY)
    assert err is not None
    assert err[0] == 400
    assert "YYYY-MM-DD" in err[1]


def test_future_execution_date_returns_400():
    err = _validate_execution_body("TRIM", {"execution_date": "2099-01-01"}, _rec(), TODAY)
    assert err == (400, "execution_date cannot be in the future")


def test_execution_before_rec_date_returns_400():
    # created_at 30 days ago but exec_date is 60 days ago → before rec
    import time as _time
    rec = {"action": "TRIM", "status": "accepted",
           "created_at": _time.time() - 10 * 86400, "ticker": "ANET"}
    err = _validate_execution_body("TRIM", {"execution_date": "2026-08-01"}, rec, TODAY)
    assert err is not None and err[0] == 400
    assert "before recommendation date" in err[1]


def test_valid_date_returns_none_for_no_action_fields():
    err = _validate_execution_body("TRIM", {"execution_date": "2026-09-05"}, _rec(), TODAY)
    assert err is None


# --- EXIT / TRIM field validation ---

def test_trim_negative_quantity_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": -10}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err == (400, "quantity must be > 0")


def test_trim_zero_price_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": 10, "execution_price": 0}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err == (400, "execution_price must be > 0")


def test_trim_quantity_exceeds_position_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": 200,
            "execution_price": 300.0, "position_shares_before": 100}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err == (400, "quantity cannot exceed position_shares_before")


def test_trim_invalid_execution_fraction_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": 10,
            "execution_price": 300.0, "execution_fraction": 1.5}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err == (400, "execution_fraction must be in (0, 1]")


def test_trim_zero_execution_fraction_returns_400():
    body = {"execution_date": "2026-09-05", "execution_fraction": 0.0}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err == (400, "execution_fraction must be in (0, 1]")


def test_trim_valid_fields_pass():
    body = {"execution_date": "2026-09-05", "quantity": 50,
            "execution_price": 300.0, "position_shares_before": 100,
            "execution_fraction": 0.5}
    err = _validate_execution_body("EXIT", body, _rec("EXIT"), TODAY)
    assert err is None


# --- SELL_CC field validation ---

def _cc_body(**kwargs):
    base = {
        "execution_date": "2026-09-05",
        "contracts": 2,
        "strike": 310.0,
        "premium": 3.50,
        "expiration": "2026-10-17",
        "position_shares_before": 200,
    }
    base.update(kwargs)
    return base


def test_cc_zero_contracts_returns_400():
    err = _validate_execution_body("SELL_CC", _cc_body(contracts=0), _rec("SELL_CC"), TODAY)
    assert err == (400, "contracts must be >= 1")


def test_cc_negative_strike_returns_400():
    err = _validate_execution_body("SELL_CC", _cc_body(strike=-1), _rec("SELL_CC"), TODAY)
    assert err == (400, "strike must be > 0")


def test_cc_zero_premium_returns_400():
    err = _validate_execution_body("SELL_CC", _cc_body(premium=0), _rec("SELL_CC"), TODAY)
    assert err == (400, "premium must be > 0")


def test_cc_expiration_before_exec_date_returns_400():
    err = _validate_execution_body("SELL_CC", _cc_body(expiration="2026-09-04"), _rec("SELL_CC"), TODAY)
    assert err == (400, "expiration cannot be before execution_date")


def test_cc_contracts_exceed_covered_shares_returns_400():
    # 3 contracts * 100 = 300 shares but only 200 available
    err = _validate_execution_body("SELL_CC", _cc_body(contracts=3, position_shares_before=200), _rec("SELL_CC"), TODAY)
    assert err is not None and err[0] == 400
    assert "exceeds covered shares" in err[1]


def test_cc_valid_returns_none():
    err = _validate_execution_body("SELL_CC", _cc_body(), _rec("SELL_CC"), TODAY)
    assert err is None


# --- unknown actions pass through ---

def test_unknown_action_no_field_validation():
    body = {"execution_date": "2026-09-05"}
    err = _validate_execution_body("NO_ACTION", body, _rec("NO_ACTION"), TODAY)
    assert err is None
