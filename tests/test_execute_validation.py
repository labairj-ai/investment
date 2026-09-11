"""Tests for _validate_execution_body (serve.py, 0092/0107)."""
import calendar
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from execution_validation import validate_execution_body as _validate_execution_body

TODAY = date.today()

def _rec(action="TRIM", status="accepted", created_days_ago=10):
    rec_date = TODAY - timedelta(days=created_days_ago)
    created_at = float(calendar.timegm(rec_date.timetuple()))
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
    import time as _time
    rec = {"action": "TRIM", "status": "accepted",
           "created_at": _time.time() - 10 * 86400, "ticker": "ANET"}
    err = _validate_execution_body("TRIM", {"execution_date": "2026-08-01"}, rec, TODAY)
    assert err is not None and err[0] == 400
    assert "before recommendation date" in err[1]


# --- 0107: required field enforcement ---

def test_trim_missing_quantity_returns_400():
    body = {"execution_date": "2026-09-05", "execution_price": 300.0}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err is not None and err[0] == 400
    assert "quantity" in err[1]


def test_trim_missing_execution_price_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": 10}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err is not None and err[0] == 400
    assert "execution_price" in err[1]


def test_exit_missing_quantity_returns_400():
    body = {"execution_date": "2026-09-05", "execution_price": 300.0}
    err = _validate_execution_body("EXIT", body, _rec("EXIT"), TODAY)
    assert err is not None and err[0] == 400
    assert "quantity" in err[1]


def test_exit_missing_execution_price_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": 50}
    err = _validate_execution_body("EXIT", body, _rec("EXIT"), TODAY)
    assert err is not None and err[0] == 400
    assert "execution_price" in err[1]


def test_sell_cc_missing_contracts_returns_400():
    body = {"execution_date": "2026-09-05",
            "strike": 310.0, "premium": 3.5, "expiration": "2026-10-17"}
    err = _validate_execution_body("SELL_CC", body, _rec("SELL_CC"), TODAY)
    assert err is not None and err[0] == 400
    assert "contracts" in err[1]


def test_sell_cc_missing_strike_returns_400():
    body = {"execution_date": "2026-09-05",
            "contracts": 2, "premium": 3.5, "expiration": "2026-10-17"}
    err = _validate_execution_body("SELL_CC", body, _rec("SELL_CC"), TODAY)
    assert err is not None and err[0] == 400
    assert "strike" in err[1]


def test_sell_cc_missing_premium_returns_400():
    body = {"execution_date": "2026-09-05",
            "contracts": 2, "strike": 310.0, "expiration": "2026-10-17"}
    err = _validate_execution_body("SELL_CC", body, _rec("SELL_CC"), TODAY)
    assert err is not None and err[0] == 400
    assert "premium" in err[1]


def test_sell_cc_missing_expiration_returns_400():
    body = {"execution_date": "2026-09-05",
            "contracts": 2, "strike": 310.0, "premium": 3.5}
    err = _validate_execution_body("SELL_CC", body, _rec("SELL_CC"), TODAY)
    assert err is not None and err[0] == 400
    assert "expiration" in err[1]


# --- EXIT / TRIM field value validation ---

def test_trim_negative_quantity_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": -10, "execution_price": 300.0}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err == (400, "quantity must be > 0")


def test_trim_zero_price_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": 10, "execution_price": 0}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err == (400, "execution_price must be > 0")


def test_trim_quantity_exceeds_position_uses_server_pos(monkeypatch):
    """0107: coverage check uses server_pos_before, ignores client body value."""
    body = {"execution_date": "2026-09-05", "quantity": 200, "execution_price": 300.0,
            "position_shares_before": 500}  # client claims 500, server says 100
    err = _validate_execution_body("TRIM", body, _rec(), TODAY, server_pos_before=100)
    assert err == (400, "quantity cannot exceed position_shares_before")


def test_trim_client_pos_before_ignored_when_no_server_value():
    """0107: client-supplied position_shares_before ignored when server_pos_before=None."""
    body = {"execution_date": "2026-09-05", "quantity": 200, "execution_price": 300.0,
            "position_shares_before": 100}  # would reject if respected
    err = _validate_execution_body("TRIM", body, _rec(), TODAY, server_pos_before=None)
    assert err is None  # no coverage check without server_pos_before


def test_trim_invalid_execution_fraction_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": 10,
            "execution_price": 300.0, "execution_fraction": 1.5}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err == (400, "execution_fraction must be in (0, 1]")


def test_trim_zero_execution_fraction_returns_400():
    body = {"execution_date": "2026-09-05", "quantity": 10,
            "execution_price": 300.0, "execution_fraction": 0.0}
    err = _validate_execution_body("TRIM", body, _rec(), TODAY)
    assert err == (400, "execution_fraction must be in (0, 1]")


def test_trim_valid_fields_pass():
    body = {"execution_date": "2026-09-05", "quantity": 50,
            "execution_price": 300.0, "execution_fraction": 0.5}
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


def test_cc_contracts_exceed_covered_shares_uses_server_pos():
    """0107: coverage check uses server_pos_before=200, not client body."""
    err = _validate_execution_body(
        "SELL_CC", _cc_body(contracts=3), _rec("SELL_CC"), TODAY,
        server_pos_before=200,
    )
    assert err is not None and err[0] == 400
    assert "exceeds covered shares" in err[1]


def test_cc_valid_returns_none():
    err = _validate_execution_body("SELL_CC", _cc_body(), _rec("SELL_CC"), TODAY,
                                   server_pos_before=200)
    assert err is None


# --- unknown actions pass through ---

def test_unknown_action_no_field_validation():
    body = {"execution_date": "2026-09-05"}
    err = _validate_execution_body("NO_ACTION", body, _rec("NO_ACTION"), TODAY)
    assert err is None
