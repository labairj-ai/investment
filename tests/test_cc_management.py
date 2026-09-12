"""Tests for the unified CC management engine (0151, 0152)."""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from covered_call_rec import evaluate_cc_management_state, _check_assignment_eligible


# ── 0151: assignment floor compares strike, not current_price ─────────────────

def test_assignment_floor_uses_strike_not_current_price():
    """0151: strike below floor must reject even when current_price > floor."""
    # current_price=205 > floor=190, but strike=180 < floor=190 → reject
    ok, reason = _check_assignment_eligible(
        ticker="TEST",
        current_price=205.0,
        strike=180.0,
        dte=5,
        delta=0.92,
        remaining_extrinsic=0.10,
        has_avoid=False,
        policy={"acceptable_assignment_min_price": 190.0},
    )
    assert not ok, "strike 180 < floor 190 should reject"
    assert "strike" in reason.lower()


def test_assignment_floor_passes_when_strike_above_floor():
    """0151: strike above floor should not block on this gate."""
    import agent_db
    with (
        patch.object(agent_db, "get_lt_lots_count", return_value=5),
    ):
        ok, reason = _check_assignment_eligible(
            ticker="TEST",
            current_price=205.0,
            strike=195.0,
            dte=5,
            delta=0.92,
            remaining_extrinsic=0.10,
            has_avoid=False,
            policy={"acceptable_assignment_min_price": 190.0},
        )
    assert ok, f"strike 195 > floor 190 should pass gate 3: {reason}"


def test_assignment_floor_not_set_passes():
    """No floor configured → gate 3 is skipped entirely."""
    import agent_db
    with (
        patch.object(agent_db, "get_lt_lots_count", return_value=5),
    ):
        ok, _ = _check_assignment_eligible(
            ticker="TEST",
            current_price=180.0,
            strike=175.0,
            dte=3,
            delta=0.91,
            remaining_extrinsic=0.05,
            has_avoid=False,
            policy={},
        )
    assert ok


# ── 0152: evaluate_cc_management_state unified hierarchy ─────────────────────

def test_cap_80_returns_btc():
    """Step 1: cap >= 80% always BUY_TO_CLOSE regardless of delta."""
    action, reason = evaluate_cc_management_state(
        ticker="TEST",
        current_price=150.0,
        strike=160.0,
        dte=30,
        delta=0.20,
        pct_captured=85.0,
        has_avoid=False,
        remaining_extrinsic=0.50,
        risk_events=[],
        policy={},
    )
    assert action == "BUY_TO_CLOSE", f"cap=85% should return BUY_TO_CLOSE, got {action}"


def test_high_delta_low_extrinsic_returns_allow_assignment():
    """Step 2: delta>=0.80, extrinsic<1%, no floor → ALLOW_ASSIGNMENT."""
    import agent_db
    with (
        patch.object(agent_db, "get_lt_lots_count", return_value=2),
    ):
        action, reason = evaluate_cc_management_state(
            ticker="TEST",
            current_price=190.0,
            strike=180.0,
            dte=5,
            delta=0.88,
            pct_captured=70.0,
            has_avoid=False,
            remaining_extrinsic=0.50,   # 0.50/190 = 0.26% < 1%
            risk_events=[],
            policy={},
        )
    assert action == "ALLOW_ASSIGNMENT", f"Should assign, got {action}: {reason}"


def test_has_avoid_returns_roll_out():
    """Step 3: risk event → ROLL_OUT (not BUY_TO_CLOSE like the old engine)."""
    import agent_db
    with (
        patch.object(agent_db, "get_lt_lots_count", return_value=0),
        patch.object(agent_db, "get_unrealized_gain", return_value=0.0),
    ):
        action, reason = evaluate_cc_management_state(
            ticker="TEST",
            current_price=155.0,
            strike=165.0,
            dte=20,
            delta=0.35,
            pct_captured=50.0,
            has_avoid=True,
            remaining_extrinsic=2.0,
            risk_events=[{"severity": "avoid", "label": "earnings"}],
            policy={},
        )
    assert action == "ROLL_OUT", f"has_avoid should give ROLL_OUT, got {action}"


def test_itm_returns_roll_up_and_out():
    """Step 6: stock above strike → ROLL_UP_AND_OUT."""
    import agent_db
    with (
        patch.object(agent_db, "get_lt_lots_count", return_value=0),
        patch.object(agent_db, "get_unrealized_gain", return_value=0.0),
    ):
        action, reason = evaluate_cc_management_state(
            ticker="TEST",
            current_price=182.0,
            strike=180.0,
            dte=15,
            delta=0.65,
            pct_captured=60.0,
            has_avoid=False,
            remaining_extrinsic=2.5,
            risk_events=[],
            policy={},
        )
    assert action == "ROLL_UP_AND_OUT", f"ITM should give ROLL_UP_AND_OUT, got {action}"


def test_otm_hold():
    """Step 7: well OTM, low delta → HOLD_CALL."""
    import agent_db
    with (
        patch.object(agent_db, "get_lt_lots_count", return_value=0),
        patch.object(agent_db, "get_unrealized_gain", return_value=0.0),
    ):
        action, reason = evaluate_cc_management_state(
            ticker="TEST",
            current_price=155.0,
            strike=170.0,
            dte=30,
            delta=0.22,
            pct_captured=40.0,
            has_avoid=False,
            remaining_extrinsic=3.0,
            risk_events=[],
            policy={},
        )
    assert action == "HOLD_CALL", f"Well OTM should give HOLD_CALL, got {action}"


def test_elevated_delta_returns_roll_up():
    """Step 7: delta>=0.30, not ITM → ROLL_UP."""
    import agent_db
    with (
        patch.object(agent_db, "get_lt_lots_count", return_value=0),
        patch.object(agent_db, "get_unrealized_gain", return_value=0.0),
    ):
        action, reason = evaluate_cc_management_state(
            ticker="TEST",
            current_price=162.0,
            strike=170.0,
            dte=30,
            delta=0.35,
            pct_captured=45.0,
            has_avoid=False,
            remaining_extrinsic=2.0,
            risk_events=[],
            policy={},
        )
    assert action == "ROLL_UP", f"delta=0.35 not ITM should give ROLL_UP, got {action}"


def test_expiring_worthless_returns_hold():
    """Step 4: DTE<=7, not ITM → HOLD_CALL (let it expire)."""
    import agent_db
    with (
        patch.object(agent_db, "get_lt_lots_count", return_value=0),
        patch.object(agent_db, "get_unrealized_gain", return_value=0.0),
    ):
        action, reason = evaluate_cc_management_state(
            ticker="TEST",
            current_price=158.0,
            strike=170.0,
            dte=4,
            delta=0.15,
            pct_captured=70.0,
            has_avoid=False,
            remaining_extrinsic=0.20,
            risk_events=[],
            policy={},
        )
    assert action == "HOLD_CALL", f"DTE=4 OTM should hold, got {action}"
