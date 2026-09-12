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
    """0103: TRIM with exec_rec uses two-component formula: f*exec_gain + (1-f)*hold_r."""
    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 500.0, "SPY@2026-01-01": 450.0}
    p1, p2 = _mock_prices(prices)
    entry_price = 180.0
    exec_price = 185.0
    f = 0.3
    exec_rec = {
        "execution_price": exec_price,
        "execution_date": "2026-01-03",
        "quantity": 30.0,
        "execution_fraction": f,
    }
    with p1, p2:
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "TRIM", "2026-01-01", "2026-04-01",
            {"trim_fraction": 0.5}, entry_price, decision="accepted",
            exec_rec=exec_rec,
        )
    hold_r = (200.0 - entry_price) / entry_price
    exec_gain = (exec_price / entry_price) - 1
    expected_actual = f * exec_gain + (1 - f) * hold_r
    assert abs(actual - expected_actual) < 0.0001, (
        f"actual={actual:.6f}, expected={expected_actual:.6f}. "
        "Formula: f*exec_gain + (1-f)*hold_r (0103)"
    )
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


# ── 0105: CC management outcome models ───────────────────────────────────────

from agents.outcome_evaluator import _compute_cc_management_returns


def test_btc_with_exec_rec_uses_actual_btc_price():
    """0125: BUY_TO_CLOSE — agent_r=stock-return-on-nav; actual_r adds slippage vs mark."""
    entry_price = 180.0
    h_price = 200.0
    btc_mark = 2.5   # C_rec: rec-date call mark (MTM basis)
    btc_exec = 2.0   # actual fill (cheaper than mark → positive slippage)
    nav = entry_price - btc_mark  # 177.5
    hold_r_nav = (h_price - entry_price) / nav
    pl = {"btc_price": btc_mark}
    exec_rec = {"execution_price": btc_exec, "execution_date": "2026-09-05"}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "BUY_TO_CLOSE", pl, entry_price, h_price, exec_rec=exec_rec,
    )
    # agent_r: close at mark → option P&L from MTM = 0 → just stock-on-nav
    assert abs(agent_r - hold_r_nav) < 0.0001, f"BTC agent_r should equal hold_r_nav={hold_r_nav:.6f}, got {agent_r}"
    # actual_r: saved (btc_mark - btc_exec) / nav
    expected_actual = hold_r_nav + (btc_mark - btc_exec) / nav
    assert abs(actual_r - expected_actual) < 0.0001, f"actual_r={actual_r:.6f} vs expected={expected_actual:.6f}"
    assert not estimated


def test_btc_no_exec_rec_falls_back_to_hold_r_nav():
    """0125: BUY_TO_CLOSE without exec_rec: actual_r = stock-on-nav, estimated=True."""
    entry_price = 180.0
    h_price = 200.0
    btc_mark = 2.5
    nav = entry_price - btc_mark  # 177.5
    hold_r_nav = (h_price - entry_price) / nav
    pl = {"btc_price": btc_mark}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "BUY_TO_CLOSE", pl, entry_price, h_price, exec_rec=None,
    )
    assert abs(actual_r - hold_r_nav) < 0.0001, f"actual_r={actual_r:.6f}, expected={hold_r_nav:.6f}"
    assert estimated


def test_allow_assignment_at_expiry_assigned_uses_nav_formula():
    """0125/0127: ALLOW_ASSIGNMENT assigned (S_exp > K): (min(S,K) - S_rec + C_rec) / nav."""
    entry_price = 175.0
    k = 185.0
    btc_mark = 2.0
    nav = entry_price - btc_mark   # 173.0
    h_price = 192.0  # > K → assigned
    pl = {"strike": k, "btc_mark": btc_mark}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "ALLOW_ASSIGNMENT", pl, entry_price, h_price, horizon_label="at_expiry",
    )
    expected = (min(h_price, k) - entry_price + btc_mark) / nav
    assert abs(actual_r - expected) < 0.0001, f"actual_r={actual_r:.6f}, expected={expected:.6f}"
    assert abs(agent_r - expected) < 0.0001
    assert not estimated


def test_allow_assignment_at_expiry_otm_uses_nav_formula():
    """0127: ALLOW_ASSIGNMENT OTM (S_exp ≤ K): call expires worthless, investor keeps shares."""
    entry_price = 175.0
    k = 185.0
    btc_mark = 2.0
    nav = entry_price - btc_mark   # 173.0
    h_price = 170.0  # < K → OTM, no assignment
    pl = {"strike": k, "btc_mark": btc_mark}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "ALLOW_ASSIGNMENT", pl, entry_price, h_price, horizon_label="at_expiry",
    )
    expected = (min(h_price, k) - entry_price + btc_mark) / nav   # (170-175+2)/173
    assert abs(actual_r - expected) < 0.0001, f"actual_r={actual_r:.6f}, expected={expected:.6f}"
    assert not estimated


def test_allow_assignment_post_horizons_lock_at_expiry_value():
    """0127: ALLOW_ASSIGNMENT 30d/90d post: locked using new_expiry_price (assigned branch)."""
    entry_price = 175.0
    k = 185.0
    btc_mark = 2.0
    nav = entry_price - btc_mark   # 173.0
    new_expiry_price = 195.0  # > K → assigned
    h_price = 205.0           # post-horizon (irrelevant once locked)
    pl = {"strike": k, "btc_mark": btc_mark}
    expected = (min(new_expiry_price, k) - entry_price + btc_mark) / nav  # (185-175+2)/173
    for label in ("30d_post", "90d_post"):
        actual_r, agent_r, estimated = _compute_cc_management_returns(
            "ALLOW_ASSIGNMENT", pl, entry_price, h_price,
            horizon_label=label, new_expiry_price=new_expiry_price,
        )
        assert abs(actual_r - expected) < 0.0001, (
            f"[{label}] locked at {expected:.4f}, got {actual_r:.4f}"
        )
        assert abs(agent_r - expected) < 0.0001
        assert not estimated


def test_roll_out_uses_sto_minus_btc_net():
    """0125: ROLL_OUT fallback (no new_strike): returns normalized by nav = entry - btc_mark."""
    entry_price = 180.0
    h_price = 200.0
    btc_mark = 2.0
    sto_mark = 4.0
    btc_exec = 1.80
    sto_exec = 4.20
    nav = entry_price - btc_mark  # 178.0
    hold_r_nav = (h_price - entry_price) / nav
    pl = {"btc_price": btc_mark, "sto_premium": sto_mark}  # no new_strike → fallback path
    exec_rec = {"execution_price": btc_exec, "sto_premium": sto_exec,
                "execution_date": "2026-09-10"}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "ROLL_OUT", pl, entry_price, h_price, exec_rec=exec_rec,
    )
    expected_actual = hold_r_nav + (sto_exec - btc_exec) / nav
    expected_agent  = hold_r_nav + (sto_mark - btc_mark) / nav
    assert abs(actual_r - expected_actual) < 0.0001, f"actual={actual_r:.6f}, expected={expected_actual:.6f}"
    assert abs(agent_r - expected_agent) < 0.0001
    assert not estimated


# ── 0114 / 0125: ROLL at_expiry and post-horizon assignment branching ─────────

def test_roll_at_expiry_capped_at_new_strike_when_assigned():
    """0125: ROLL at_expiry assigned — capped at new_strike, normalized by nav."""
    entry_price = 180.0
    new_strike = 195.0
    h_price = 210.0     # > new_strike → assigned
    btc_mark, sto_mark = 3.0, 4.5
    btc_exec, sto_exec = 2.8, 4.6
    nav = entry_price - btc_mark  # 177.0
    net_credit = sto_exec - btc_exec   # 1.8
    hold_r_nav = (h_price - entry_price) / nav
    pl = {"new_strike": new_strike, "btc_price": btc_mark, "sto_premium": sto_mark}
    exec_rec = {"execution_price": btc_exec, "sto_premium": sto_exec,
                "execution_date": "2026-09-01"}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "ROLL_OUT", pl, entry_price, h_price, exec_rec=exec_rec,
        horizon_label="at_expiry",
    )
    expected_actual = (new_strike - entry_price) / nav + net_credit / nav
    expected_agent  = (new_strike - entry_price) / nav + (sto_mark - btc_mark) / nav
    assert abs(actual_r - expected_actual) < 0.0001, f"actual_r={actual_r:.6f} expected={expected_actual:.6f}"
    assert abs(agent_r - expected_agent) < 0.0001
    assert actual_r < hold_r_nav + net_credit / nav, "Assigned path must be capped below uncapped"
    assert not estimated


def test_roll_at_expiry_uncapped_when_expired():
    """0125: ROLL at_expiry OTM — stock return uncapped, normalized by nav."""
    entry_price = 180.0
    new_strike = 195.0
    h_price = 188.0     # < new_strike → expired worthless
    btc_mark, sto_mark = 3.0, 4.5
    btc_exec, sto_exec = 3.1, 4.4
    nav = entry_price - btc_mark  # 177.0
    net_credit = sto_exec - btc_exec   # 1.3
    hold_r_nav = (h_price - entry_price) / nav
    pl = {"new_strike": new_strike, "btc_price": btc_mark, "sto_premium": sto_mark}
    exec_rec = {"execution_price": btc_exec, "sto_premium": sto_exec,
                "execution_date": "2026-09-01"}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "ROLL_OUT", pl, entry_price, h_price, exec_rec=exec_rec,
        horizon_label="at_expiry",
    )
    expected_actual = hold_r_nav + net_credit / nav
    assert abs(actual_r - expected_actual) < 0.0001, f"Expired path uncapped: {actual_r:.6f}"
    assert not estimated


def test_roll_post_horizon_locks_at_assignment_when_assigned():
    """0125: ROLL 30d_post assigned — locked at assignment level, normalized by nav."""
    entry_price = 180.0
    new_strike = 195.0
    new_expiry_price = 205.0
    h_price = 215.0
    btc_mark, sto_mark = 3.0, 4.5
    btc_exec, sto_exec = 2.8, 4.6
    nav = entry_price - btc_mark  # 177.0
    net_credit = sto_exec - btc_exec  # 1.8
    pl = {"new_strike": new_strike, "btc_price": btc_mark, "sto_premium": sto_mark}
    exec_rec = {"execution_price": btc_exec, "sto_premium": sto_exec,
                "execution_date": "2026-09-01"}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "ROLL_OUT", pl, entry_price, h_price, exec_rec=exec_rec,
        horizon_label="30d_post", new_expiry_price=new_expiry_price,
    )
    expected_actual = (new_strike - entry_price) / nav + net_credit / nav
    assert abs(actual_r - expected_actual) < 0.0001, f"Post-assignment should lock: {actual_r:.6f}"
    assert not estimated


def test_roll_post_horizon_uses_hold_r_when_expired():
    """0125: ROLL 30d_post OTM — stock continues to post-horizon, normalized by nav."""
    entry_price = 180.0
    new_strike = 195.0
    new_expiry_price = 190.0   # < new_strike → expired
    h_price = 205.0
    btc_mark, sto_mark = 3.0, 4.5
    btc_exec, sto_exec = 2.9, 4.5
    nav = entry_price - btc_mark  # 177.0
    net_credit = sto_exec - btc_exec  # 1.6
    hold_r_nav = (h_price - entry_price) / nav
    pl = {"new_strike": new_strike, "btc_price": btc_mark, "sto_premium": sto_mark}
    exec_rec = {"execution_price": btc_exec, "sto_premium": sto_exec,
                "execution_date": "2026-09-01"}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "ROLL_OUT", pl, entry_price, h_price, exec_rec=exec_rec,
        horizon_label="30d_post", new_expiry_price=new_expiry_price,
    )
    expected_actual = hold_r_nav + net_credit / nav
    assert abs(actual_r - expected_actual) < 0.0001, f"Expired path at 30d_post: {actual_r:.6f}"
    assert not estimated


# ── 0136: multi-hop chain evaluation ──────────────────────────────────────────

def test_roll_open_chain_child_stays_estimated():
    """0140/0136: open child (replacement call still pending) keeps outcome estimated."""
    entry_price = 180.0
    new_strike = 195.0
    h_price = 205.0  # > new_strike → would normally cap
    btc_mark, sto_mark = 3.0, 4.5
    btc_exec, sto_exec = 2.8, 4.6
    nav = entry_price - btc_mark
    pl = {"new_strike": new_strike, "btc_price": btc_mark, "sto_premium": sto_mark}
    exec_rec = {"execution_price": btc_exec, "sto_premium": sto_exec}
    import agents.outcome_evaluator as oe
    import agent_db
    with (
        patch.object(agent_db, "has_chain_child", return_value=True),
        patch.object(agent_db, "get_completed_chain_child", return_value=None),
    ):
        actual_r, agent_r, estimated = _compute_cc_management_returns(
            "ROLL_OUT", pl, entry_price, h_price, exec_rec=exec_rec,
            horizon_label="at_expiry", rec_id=42,
        )
    assert estimated, "Open chain child must keep outcome estimated"


def test_roll_completed_btc_child_uses_uncapped_stock_return():
    """0136: BTC child — replacement call bought back, stock return is uncapped."""
    entry_price = 180.0
    new_strike = 195.0
    h_price = 210.0  # > new_strike, but call was BTC'd so stock is uncapped
    btc_mark, sto_mark = 3.0, 4.5
    btc_exec, sto_exec = 2.8, 4.6
    nav = entry_price - btc_mark  # 177.0
    net_credit = sto_exec - btc_exec  # 1.8
    hold_r_nav = (h_price - entry_price) / nav
    pl = {"new_strike": new_strike, "btc_price": btc_mark, "sto_premium": sto_mark}
    exec_rec = {"execution_price": btc_exec, "sto_premium": sto_exec}
    import agent_db
    with (
        patch.object(agent_db, "has_chain_child", return_value=False),
        patch.object(agent_db, "get_completed_chain_child", return_value={
            "id": 99, "action": "BUY_TO_CLOSE",
            "payload": {"btc_price": 1.0}, "exec_rec": None,
        }),
    ):
        actual_r, agent_r, estimated = _compute_cc_management_returns(
            "ROLL_OUT", pl, entry_price, h_price, exec_rec=exec_rec,
            horizon_label="at_expiry", rec_id=42,
        )
    expected_actual = hold_r_nav + net_credit / nav  # uncapped
    assert abs(actual_r - expected_actual) < 0.0001, f"BTC child must use uncapped hold_r: {actual_r:.6f}"
    assert not estimated


def test_roll_completed_assignment_child_caps_at_child_strike():
    """0136: ALLOW_ASSIGNMENT child — stock capped at child strike, not new_strike."""
    entry_price = 180.0
    new_strike = 195.0   # original roll strike
    child_strike = 198.0  # assignment happened at a slightly different strike
    h_price = 215.0  # > both strikes
    btc_mark, sto_mark = 3.0, 4.5
    btc_exec, sto_exec = 2.8, 4.6
    nav = entry_price - btc_mark  # 177.0
    net_credit = sto_exec - btc_exec  # 1.8
    pl = {"new_strike": new_strike, "btc_price": btc_mark, "sto_premium": sto_mark}
    exec_rec = {"execution_price": btc_exec, "sto_premium": sto_exec}
    import agent_db
    with (
        patch.object(agent_db, "has_chain_child", return_value=False),
        patch.object(agent_db, "get_completed_chain_child", return_value={
            "id": 99, "action": "ALLOW_ASSIGNMENT",
            "payload": {"strike": child_strike}, "exec_rec": None,
        }),
    ):
        actual_r, agent_r, estimated = _compute_cc_management_returns(
            "ROLL_OUT", pl, entry_price, h_price, exec_rec=exec_rec,
            horizon_label="at_expiry", rec_id=42,
        )
    expected_actual = (child_strike - entry_price) / nav + net_credit / nav
    assert abs(actual_r - expected_actual) < 0.0001, f"Assignment child caps at child_strike: {actual_r:.6f}"
    assert not estimated


def test_roll_multi_hop_child_stays_estimated():
    """0136: another ROLL child (multi-hop) keeps outcome estimated."""
    entry_price = 180.0
    new_strike = 195.0
    h_price = 205.0
    btc_mark, sto_mark = 3.0, 4.5
    btc_exec, sto_exec = 2.8, 4.6
    pl = {"new_strike": new_strike, "btc_price": btc_mark, "sto_premium": sto_mark}
    exec_rec = {"execution_price": btc_exec, "sto_premium": sto_exec}
    import agent_db
    with (
        patch.object(agent_db, "has_chain_child", return_value=False),
        patch.object(agent_db, "get_completed_chain_child", return_value={
            "id": 99, "action": "ROLL_OUT",
            "payload": {"new_strike": 200.0}, "exec_rec": None,
        }),
    ):
        actual_r, agent_r, estimated = _compute_cc_management_returns(
            "ROLL_OUT", pl, entry_price, h_price, exec_rec=exec_rec,
            horizon_label="at_expiry", rec_id=42,
        )
    assert estimated, "Multi-hop ROLL child must keep outcome estimated"


# ── 0126: HOLD_CALL terminal-payoff economics ─────────────────────────────────

def test_hold_call_at_expiry_assigned():
    """0126: HOLD_CALL at_expiry assigned — (min(S_exp,K) - S_rec + C_rec) / nav."""
    entry_price = 180.0
    k = 185.0
    btc_mark = 2.0   # C_rec
    nav = entry_price - btc_mark  # 178.0
    h_price = 195.0  # > K → assigned at K
    pl = {"strike": k, "btc_mark": btc_mark, "expiration": "2026-12-20"}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "HOLD_CALL", pl, entry_price, h_price, horizon_label="at_expiry",
    )
    expected = (min(h_price, k) - entry_price + btc_mark) / nav  # (185-180+2)/178
    assert abs(actual_r - expected) < 0.0001, f"actual_r={actual_r:.6f}, expected={expected:.6f}"
    assert abs(agent_r - expected) < 0.0001, "agent_r should equal actual_r (rec was followed)"
    assert not estimated


def test_hold_call_at_expiry_otm():
    """0126: HOLD_CALL at_expiry OTM — call expires worthless, investor keeps shares."""
    entry_price = 180.0
    k = 185.0
    btc_mark = 2.0
    nav = entry_price - btc_mark  # 178.0
    h_price = 175.0  # < K → OTM, investor keeps shares at depressed price
    pl = {"strike": k, "btc_mark": btc_mark}
    actual_r, agent_r, estimated = _compute_cc_management_returns(
        "HOLD_CALL", pl, entry_price, h_price, horizon_label="at_expiry",
    )
    expected = (min(h_price, k) - entry_price + btc_mark) / nav  # (175-180+2)/178
    assert abs(actual_r - expected) < 0.0001
    assert not estimated


def test_hold_call_post_horizon_locks_at_expiry_value():
    """0126: HOLD_CALL post-horizons lock at at-expiry value using new_expiry_price."""
    entry_price = 180.0
    k = 185.0
    btc_mark = 2.0
    nav = entry_price - btc_mark  # 178.0
    new_expiry_price = 195.0  # S at expiry > K → assigned
    h_price = 210.0            # post-horizon price (irrelevant once locked)
    pl = {"strike": k, "btc_mark": btc_mark}
    expected = (min(new_expiry_price, k) - entry_price + btc_mark) / nav  # (185-180+2)/178
    for label in ("30d_post", "90d_post"):
        actual_r, agent_r, estimated = _compute_cc_management_returns(
            "HOLD_CALL", pl, entry_price, h_price,
            horizon_label=label, new_expiry_price=new_expiry_price,
        )
        assert abs(actual_r - expected) < 0.0001, f"[{label}] expected={expected:.4f} got={actual_r:.4f}"
        assert abs(agent_r - expected) < 0.0001
        assert not estimated


# ── 0106: CC post-expiry state-transition math ────────────────────────────────

def test_sell_cc_assigned_path_post_horizons_locked_at_assignment():
    """0113: when S_exp > K, 30d/90d post actual_r is locked at assignment return, not 0."""
    entry_price = 180.0
    k = 190.0
    premium = 3.0
    prices = {
        "ANET": 220.0,              # S at 30d post — irrelevant once assigned
        "ANET@2026-01-01": entry_price,
        "ANET@2026-03-21": 200.0,  # S_exp > K=190 → assigned
        "SPY": 500.0, "SPY@2026-01-01": 450.0,
    }
    p1, p2 = _mock_prices(prices)
    exec_rec = {
        "execution_price": premium,
        "execution_date": "2026-01-02",
        "strike": k,
    }
    expected_assign = (k - entry_price + premium) / entry_price
    with p1, p2:
        actual_r, agent_r, hold_r, spy_r, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "SELL_CC", "2026-01-01", "2026-04-20",
            {"premium": premium, "strike": str(k)}, entry_price, decision="accepted",
            exec_rec=exec_rec,
            horizon_label="30d_post",
            cc_expiry_date="2026-03-21",
        )
    assert abs(actual_r - expected_assign) < 0.0001, (
        f"Assigned call 30d_post should lock at {expected_assign:.4f}, got {actual_r}"
    )
    assert abs(cc_ret - expected_assign) < 0.0001, (
        f"CC strategy return should lock at {expected_assign:.4f}, got {cc_ret}"
    )
    assert not estimated


def test_sell_cc_expired_path_post_horizons_no_strike_cap():
    """0106: when S_exp <= K, 30d_post actual_r = (S_30 - S0 + premium) / S0 (no cap)."""
    prices = {
        "ANET": 230.0,              # S at 30d post — above K
        "ANET@2026-01-01": 180.0,   # entry
        "ANET@2026-03-21": 185.0,   # S_exp <= K=190 → expired worthless
        "SPY": 500.0, "SPY@2026-01-01": 450.0,
    }
    p1, p2 = _mock_prices(prices)
    exec_rec = {
        "execution_price": 3.0,
        "execution_date": "2026-01-02",
        "strike": 190.0,
    }
    with p1, p2:
        actual_r, agent_r, hold_r, spy_r, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "SELL_CC", "2026-01-01", "2026-04-20",
            {"premium": 3.0, "strike": "190.0"}, 180.0, decision="accepted",
            exec_rec=exec_rec,
            horizon_label="30d_post",
            cc_expiry_date="2026-03-21",
        )
    # Call expired worthless → investor holds uncapped stock
    expected_actual = (230.0 - 180.0 + 3.0) / 180.0
    assert abs(actual_r - expected_actual) < 0.0001, (
        f"Expired call 30d_post should use uncapped formula, got {actual_r:.4f}"
    )
    assert not estimated


def test_sell_cc_at_expiry_always_uses_min_formula():
    """0106: at_expiry horizon always uses min(S_exp, K) regardless of assignment."""
    prices = {
        "ANET": 200.0,
        "ANET@2026-01-01": 180.0,
        "SPY": 500.0, "SPY@2026-01-01": 450.0,
    }
    p1, p2 = _mock_prices(prices)
    exec_rec = {"execution_price": 3.0, "execution_date": "2026-01-02", "strike": 190.0}
    with p1, p2:
        actual_r, agent_r, hold_r, spy_r, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "SELL_CC", "2026-01-01", "2026-03-21",
            {"premium": 3.0, "strike": "190.0"}, 180.0, decision="accepted",
            exec_rec=exec_rec,
            horizon_label="at_expiry",
            cc_expiry_date="2026-03-21",
        )
    # at_expiry: S=200 > K=190 → min(200, 190)=190
    expected_actual = (190.0 - 180.0 + 3.0) / 180.0
    assert abs(actual_r - expected_actual) < 0.0001
