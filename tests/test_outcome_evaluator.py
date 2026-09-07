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
    """0071: accepted EXIT without exec_rec → actual_r=None, estimated=True."""
    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 500.0, "SPY@2026-01-01": 450.0}
    p1, p2 = _mock_prices(prices)
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "EXIT", "2026-01-01", "2026-04-01",
            {}, 180.0, decision="accepted",
        )
    # 0071: without exec_rec, we cannot confirm the return — it should be estimated
    assert actual is None
    assert estimated is True


def test_accepted_exit_with_execution_uses_exec_price():
    """0070: accepted EXIT with exec_rec → actual_r computed from execution_price."""
    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 500.0, "SPY@2026-01-01": 450.0}
    p1, p2 = _mock_prices(prices)
    exec_rec = {
        "execution_price": 190.0,
        "execution_date": "2026-01-05",
        "quantity": 50.0,
    }
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "EXIT", "2026-01-01", "2026-04-01",
            {}, 180.0, decision="accepted",
            exec_rec=exec_rec,
        )
    expected_actual = (190.0 - 180.0) / 180.0
    assert abs(actual - expected_actual) < 0.001
    assert not estimated


def test_trim_with_execution_fraction():
    """0072: TRIM with exec_rec.execution_fraction uses that fraction."""
    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 500.0, "SPY@2026-01-01": 450.0}
    p1, p2 = _mock_prices(prices)
    exec_rec = {
        "execution_price": 185.0,
        "execution_date": "2026-01-03",
        "quantity": 30.0,
        "execution_fraction": 0.3,
    }
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "TRIM", "2026-01-01", "2026-04-01",
            {"trim_fraction": 0.5}, 180.0, decision="accepted",
            exec_rec=exec_rec,
        )
    hold_r = (200.0 - 180.0) / 180.0
    expected_actual = (1 - 0.3) * hold_r
    assert abs(actual - expected_actual) < 0.001
    assert not estimated


def test_sell_cc_with_exec_rec_computes_actual_from_premium_and_strike():
    """0073: SELL_CC with exec_rec computes actual_r from real premium+strike."""
    prices = {"ANET": 185.0, "ANET@2026-01-01": 180.0, "SPY": 500.0, "SPY@2026-01-01": 450.0}
    p1, p2 = _mock_prices(prices)
    exec_rec = {
        "execution_price": 3.0,   # premium per share
        "execution_date": "2026-01-02",
        "strike": 190.0,
    }
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "SELL_CC", "2026-01-01", "2026-04-01",
            {"premium": 2.5, "strike": 195.0}, 180.0, decision="accepted",
            exec_rec=exec_rec,
        )
    # actual_exit = min(185.0, 190.0) = 185.0
    # actual_r = (185.0 - 180.0 + 3.0) / 180.0
    expected_actual = (min(185.0, 190.0) - 180.0 + 3.0) / 180.0
    assert abs(actual - expected_actual) < 0.001
    assert not estimated
    # Verify it differs from the payload-based cc_strategy_return
    # (cc_ret uses pl.premium=2.5 and pl.strike=195.0)
    assert cc_ret is not None
    assert abs(actual - cc_ret) > 0.001, "CC actual should differ from strategy return when exec differs"


# ── 0091: multi-fill execution aggregation ────────────────────────────────────

def test_aggregate_executions_stock_weighted_avg():
    """Two TRIM fills: weighted avg price and total_quantity are correct."""
    import agent_db
    fills = [
        {"action": "TRIM", "quantity": 30.0, "execution_price": 155.0,
         "execution_date": "2026-09-01", "position_shares_before": 100.0,
         "execution_fraction": None, "strike": None, "premium": None, "contracts": None},
        {"action": "TRIM", "quantity": 20.0, "execution_price": 158.0,
         "execution_date": "2026-09-05", "position_shares_before": None,
         "execution_fraction": None, "strike": None, "premium": None, "contracts": None},
    ]
    summary = agent_db.aggregate_executions(fills, "TRIM")
    assert summary is not None
    assert abs(summary.total_quantity - 50.0) < 0.001
    expected_price = (30 * 155 + 20 * 158) / 50
    assert abs(summary.weighted_avg_price - expected_price) < 0.01
    assert summary.get("execution_price") == summary.weighted_avg_price
    assert summary.execution_date == "2026-09-05"
    assert summary.first_execution_date == "2026-09-01"


def test_aggregate_executions_cc_premium_weighted():
    """Two SELL_CC fills: weighted avg premium and total_premium_cash."""
    import agent_db
    fills = [
        {"action": "SELL_CC", "contracts": 1, "premium": 3.50, "execution_price": 3.50,
         "execution_date": "2026-09-01", "quantity": None, "strike": 175.0,
         "position_shares_before": None, "execution_fraction": None},
        {"action": "SELL_CC", "contracts": 1, "premium": 3.80, "execution_price": 3.80,
         "execution_date": "2026-09-01", "quantity": None, "strike": 175.0,
         "position_shares_before": None, "execution_fraction": None},
    ]
    summary = agent_db.aggregate_executions(fills, "SELL_CC")
    assert summary is not None
    assert summary.total_contracts == 2
    expected_premium = (3.50 + 3.80) / 2
    assert abs(summary.weighted_avg_premium - expected_premium) < 0.01
    expected_cash = 2 * 100 * expected_premium
    assert abs(summary.total_premium_cash - expected_cash) < 0.01
    assert summary.strike == 175.0


def test_aggregate_executions_empty_returns_none():
    import agent_db
    assert agent_db.aggregate_executions([], "TRIM") is None


def test_aggregate_executions_execution_fraction_computed(agent_db_module=None):
    """When no explicit execution_fraction, compute from position_shares_before."""
    import agent_db
    fills = [
        {"action": "TRIM", "quantity": 30.0, "execution_price": 155.0,
         "execution_date": "2026-09-01", "position_shares_before": 100.0,
         "execution_fraction": None, "strike": None, "premium": None, "contracts": None},
    ]
    summary = agent_db.aggregate_executions(fills, "TRIM")
    assert abs(summary.execution_fraction - 0.30) < 0.001
