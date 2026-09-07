"""Tests for outcome_evaluator.py — TRIM/ALLOCATE/REBALANCE scenario math."""
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.outcome_evaluator import _compute_scenarios


def _mock_prices(price_map: dict):
    """Context manager: patch _ticker_price_at and _spy_price_at with dict lookup."""
    from unittest.mock import MagicMock
    import agents.outcome_evaluator as oe

    def fake_ticker_price(ticker, date_str):
        return price_map.get(f"{ticker}@{date_str}") or price_map.get(ticker)

    def fake_spy_price(date_str):
        return price_map.get(f"SPY@{date_str}") or price_map.get("SPY")

    return (
        patch.object(oe, "_ticker_price_at", side_effect=fake_ticker_price),
        patch.object(oe, "_spy_price_at", side_effect=fake_spy_price),
    )


def test_hold_scenario():
    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 500.0, "SPY@2026-01-01": 450.0}
    p1, p2 = _mock_prices(prices)
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "HOLD", "2026-01-01", "2026-04-01",
            {}, 180.0, decision="accepted",
        )
    expected_hold = (200.0 - 180.0) / 180.0
    assert abs(hold - expected_hold) < 0.001
    assert abs(agent - hold) < 0.001  # HOLD: agent_r == hold_r


def test_trim_scenario_no_replacement():
    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 500.0, "SPY@2026-01-01": 450.0}
    p1, p2 = _mock_prices(prices)
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "TRIM", "2026-01-01", "2026-04-01",
            {"trim_fraction": 0.4}, 180.0, decision="accepted",
        )
    expected_hold = (200.0 - 180.0) / 180.0
    expected_agent = 0.6 * expected_hold  # 40% trimmed to cash (return=0)
    assert abs(agent - expected_agent) < 0.001
    assert agent != hold, "TRIM agent_r should differ from hold_r"


def test_trim_scenario_with_replacement():
    prices = {
        "ANET": 200.0, "ANET@2026-01-01": 180.0,
        "SCHD": 85.0,  "SCHD@2026-01-01": 78.0,
        "SPY": 500.0,  "SPY@2026-01-01": 450.0,
    }
    p1, p2 = _mock_prices(prices)
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "TRIM", "2026-01-01", "2026-04-01",
            {"trim_fraction": 0.5, "replacement_ticker": "SCHD"}, 180.0, decision="accepted",
        )
    hold_r = (200.0 - 180.0) / 180.0
    schd_r = (85.0 - 78.0) / 78.0
    expected_agent = 0.5 * hold_r + 0.5 * schd_r
    assert abs(agent - expected_agent) < 0.001


def test_allocate_scenario():
    prices = {
        "NFLX": 750.0, "NFLX@2026-01-01": 700.0,
        "SPY": 500.0,  "SPY@2026-01-01": 450.0,
    }
    p1, p2 = _mock_prices(prices)
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "NFLX", "ALLOCATE", "2026-01-01", "2026-04-01",
            {"ticker": "NFLX"}, 700.0, decision="accepted",
        )
    expected_agent = (750.0 - 700.0) / 700.0
    assert abs(agent - expected_agent) < 0.001


def test_rejected_exit_equals_hold():
    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 500.0, "SPY@2026-01-01": 450.0}
    p1, p2 = _mock_prices(prices)
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "EXIT", "2026-01-01", "2026-04-01",
            {}, 180.0, decision="rejected",
        )
    assert not estimated
    assert abs(actual - hold) < 0.001


def test_accepted_exit_actual_zero():
    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 500.0, "SPY@2026-01-01": 450.0}
    p1, p2 = _mock_prices(prices)
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "EXIT", "2026-01-01", "2026-04-01",
            {}, 180.0, decision="accepted",
        )
    assert actual == 0.0
    assert not estimated
