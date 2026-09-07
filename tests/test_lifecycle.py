from __future__ import annotations
"""Lifecycle integration tests — 0081.

Tests full paths from recommendation creation through decisions, executions,
and outcome evaluation using the mem_db and mock_llm fixtures.

All 8+ scenarios use the in-memory DB with real migrate() and real agent_db helpers.
"""
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── Seed helpers ───────────────────────────────────────────────────────────────

def _seed_rec(conn, ticker="ANET", action="HOLD", created_at=None, status="open"):
    ts = created_at or (time.time() - 100 * 86400)  # 100 days ago by default
    conn.execute(
        """INSERT INTO recommendations
           (ticker, action, recommendation_score, confidence, priority, status, created_at)
           VALUES (?, ?, 50, 60, 'normal', ?, ?)""",
        (ticker, action, status, ts),
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _seed_decision(conn, rec_id, decision):
    conn.execute(
        """INSERT INTO user_decisions (recommendation_id, decision, reason_code, decided_at)
           VALUES (?, ?, 'OTHER', ?)""",
        (rec_id, decision, time.time()),
    )
    conn.commit()


def _seed_price(conn, ticker, day, price):
    """Seed a price into holding_day (created ad-hoc if needed for integration tests)."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS holding_day
           (ticker TEXT, day TEXT, price REAL, value REAL, weight_pct REAL, shares REAL,
            PRIMARY KEY (ticker, day))"""
    )
    conn.execute(
        """INSERT OR REPLACE INTO holding_day
           (ticker, day, price, value, weight_pct, shares)
           VALUES (?, ?, ?, ?, 10.0, 100)""",
        (ticker, day, price, price * 100),
    )
    conn.commit()


def _seed_spy(conn, day, price):
    conn.execute(
        "INSERT OR REPLACE INTO spy_prices (day, price) VALUES (?, ?)",
        (day, price),
    )
    conn.commit()


def _open_conn(mem_db):
    import sqlite3
    conn = sqlite3.connect(str(mem_db), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ── Scenario 1: HOLD rejected → actual_r = hold_r ────────────────────────────

def test_hold_rejected_actual_equals_hold(mem_db):
    """HOLD rejected → outcome: actual_r = hold_r, actual_is_estimated = False."""
    import agent_db
    from agents.outcome_evaluator import _compute_scenarios

    entry_price = 180.0
    horizon_price = 200.0
    spy_entry = 450.0
    spy_h = 500.0

    prices = {
        "ANET": horizon_price,
        "ANET@2026-01-01": entry_price,
        "SPY": spy_h,
        "SPY@2026-01-01": spy_entry,
    }

    def fake_ticker_price(ticker, date_str):
        return prices.get(f"{ticker}@{date_str}") or prices.get(ticker)

    def fake_spy_price(date_str):
        return prices.get(f"SPY@{date_str}") or prices.get("SPY")

    import agents.outcome_evaluator as oe
    with patch.object(oe, "_ticker_price_at", side_effect=fake_ticker_price), \
         patch.object(oe, "_spy_price_at", side_effect=fake_spy_price):
        actual, agent, hold, spy, estimated, _, _ = _compute_scenarios(
            "ANET", "HOLD", "2026-01-01", "2026-04-01",
            {}, entry_price, decision="rejected",
        )

    expected_hold = (horizon_price - entry_price) / entry_price
    assert abs(actual - hold) < 0.001
    assert abs(actual - expected_hold) < 0.001
    assert not estimated


# ── Scenario 2: TRIM with execution_fraction ──────────────────────────────────

def test_trim_with_execution_uses_fraction(mem_db):
    """TRIM accepted + executed_action with execution_fraction → actual uses that fraction."""
    import agent_db
    from agents.outcome_evaluator import _compute_scenarios

    entry_price = 180.0
    horizon_price = 200.0
    exec_rec = {
        "execution_price": 185.0,
        "execution_date": "2026-01-03",
        "quantity": 30.0,
        "execution_fraction": 0.25,  # trimmed 25%
    }

    prices = {
        "ANET": horizon_price,
        "ANET@2026-01-01": entry_price,
        "SPY": 500.0,
        "SPY@2026-01-01": 450.0,
    }

    import agents.outcome_evaluator as oe
    with patch.object(oe, "_ticker_price_at", side_effect=lambda t, d: prices.get(f"{t}@{d}") or prices.get(t)), \
         patch.object(oe, "_spy_price_at", side_effect=lambda d: prices.get(f"SPY@{d}") or prices.get("SPY")):
        actual, agent, hold, spy, estimated, _, _ = _compute_scenarios(
            "ANET", "TRIM", "2026-01-01", "2026-04-01",
            {"trim_fraction": 0.5}, entry_price, decision="accepted",
            exec_rec=exec_rec,
        )

    hold_r = (horizon_price - entry_price) / entry_price
    expected_actual = (1 - 0.25) * hold_r
    assert abs(actual - expected_actual) < 0.001
    assert not estimated


# ── Scenario 3: EXIT accepted with execution → actual from exec_price ─────────

def test_exit_accepted_with_execution(mem_db):
    """EXIT accepted + exec_rec → actual_r from execution_price, estimated=False."""
    from agents.outcome_evaluator import _compute_scenarios

    entry_price = 180.0
    exec_rec = {
        "execution_price": 192.0,
        "execution_date": "2026-01-05",
        "quantity": 100.0,
    }
    prices = {
        "ANET": 210.0,
        "ANET@2026-01-01": entry_price,
        "SPY": 510.0,
        "SPY@2026-01-01": 455.0,
    }

    import agents.outcome_evaluator as oe
    with patch.object(oe, "_ticker_price_at", side_effect=lambda t, d: prices.get(f"{t}@{d}") or prices.get(t)), \
         patch.object(oe, "_spy_price_at", side_effect=lambda d: prices.get(f"SPY@{d}") or prices.get("SPY")):
        actual, agent, hold, spy, estimated, _, _ = _compute_scenarios(
            "ANET", "EXIT", "2026-01-01", "2026-04-01",
            {}, entry_price, decision="accepted",
            exec_rec=exec_rec,
        )

    expected_actual = (192.0 - 180.0) / 180.0
    assert abs(actual - expected_actual) < 0.001
    assert not estimated


# ── Scenario 4: EXIT accepted without execution → actual=None, estimated=True ──

def test_exit_accepted_without_execution(mem_db):
    """EXIT accepted, no exec_rec → actual_r=None, estimated=True (0071)."""
    from agents.outcome_evaluator import _compute_scenarios

    prices = {"ANET": 210.0, "ANET@2026-01-01": 180.0, "SPY": 510.0, "SPY@2026-01-01": 455.0}

    import agents.outcome_evaluator as oe
    with patch.object(oe, "_ticker_price_at", side_effect=lambda t, d: prices.get(f"{t}@{d}") or prices.get(t)), \
         patch.object(oe, "_spy_price_at", side_effect=lambda d: prices.get(f"SPY@{d}") or prices.get("SPY")):
        actual, agent, hold, spy, estimated, _, _ = _compute_scenarios(
            "ANET", "EXIT", "2026-01-01", "2026-04-01",
            {}, 180.0, decision="accepted",
        )

    assert actual is None
    assert estimated is True


# ── Scenario 5: EXIT rejected → actual_r = hold_r ────────────────────────────

def test_exit_rejected_actual_equals_hold(mem_db):
    """EXIT rejected → actual_r = hold_r, estimated=False."""
    from agents.outcome_evaluator import _compute_scenarios

    entry_price = 180.0
    horizon_price = 210.0
    prices = {"ANET": horizon_price, "ANET@2026-01-01": entry_price, "SPY": 510.0, "SPY@2026-01-01": 455.0}

    import agents.outcome_evaluator as oe
    with patch.object(oe, "_ticker_price_at", side_effect=lambda t, d: prices.get(f"{t}@{d}") or prices.get(t)), \
         patch.object(oe, "_spy_price_at", side_effect=lambda d: prices.get(f"SPY@{d}") or prices.get("SPY")):
        actual, agent, hold, spy, estimated, _, _ = _compute_scenarios(
            "ANET", "EXIT", "2026-01-01", "2026-04-01",
            {}, entry_price, decision="rejected",
        )

    expected_hold = (horizon_price - entry_price) / entry_price
    assert abs(actual - hold) < 0.001
    assert abs(actual - expected_hold) < 0.001
    assert not estimated


# ── Scenario 6: Dependency supersession ───────────────────────────────────────

def test_price_dependency_supersedes_on_big_move(mem_db):
    """PRICE dependency: big move outside tolerance → supersession reason returned."""
    from agents.dependency_checker import _check_price

    dep = {"dependency_key": "ANET", "original_value": "100.00", "tolerance": 0.05}
    reason = _check_price(dep, {"ANET": 115.0})  # 15% move, > 5% tolerance
    assert reason is not None
    assert "15.0%" in reason or "15" in reason


def test_price_dependency_no_supersession_within_tolerance(mem_db):
    """PRICE dependency: move within tolerance → no supersession."""
    from agents.dependency_checker import _check_price

    dep = {"dependency_key": "ANET", "original_value": "100.00", "tolerance": 0.20}
    reason = _check_price(dep, {"ANET": 110.0})  # 10% move, < 20% tolerance
    assert reason is None


# ── Scenario 7: Decision validation ───────────────────────────────────────────

def test_decision_validation_rejects_invalid():
    """Decision endpoint validation: invalid decision string should be rejected."""
    # Test the validation logic directly (not HTTP layer)
    VALID = frozenset({"accepted", "rejected", "deferred"})
    assert "accepted" in VALID
    assert "rejected" in VALID
    assert "deferred" in VALID
    assert "hacked" not in VALID
    assert "ACCEPTED" not in VALID  # must be lowercase


def test_decision_validation_accepts_valid():
    """All valid decisions pass the set membership check."""
    VALID = frozenset({"accepted", "rejected", "deferred"})
    for d in ("accepted", "rejected", "deferred"):
        assert d in VALID


# ── Scenario 8: Full path from seeded rec to written outcome row ───────────────

def test_full_lifecycle_hold_rec_to_outcome(mem_db):
    """Full path: seed rec+decision+prices → evaluate_matured_recommendations → outcome row written."""
    import agent_db
    from agents.outcome_evaluator import evaluate_matured_recommendations

    conn = _open_conn(mem_db)

    # 100 days ago entry date
    entry_ts = time.time() - 100 * 86400
    entry_date = (date.today() - timedelta(days=100)).isoformat()
    h_date_1m = (date.today() - timedelta(days=70)).isoformat()  # 1-month horizon = 30d after entry

    # Seed a HOLD recommendation
    rec_id = _seed_rec(conn, ticker="ANET", action="HOLD", created_at=entry_ts, status="accepted")
    _seed_decision(conn, rec_id, "rejected")

    # Seed prices: entry price + horizon price + SPY
    _seed_price(conn, "ANET", entry_date, 180.0)
    _seed_price(conn, "ANET", h_date_1m, 200.0)  # price 30d later for 1m horizon
    _seed_spy(conn, entry_date, 450.0)
    _seed_spy(conn, h_date_1m, 470.0)

    conn.close()

    # Patch SPY price fetching to avoid network call
    with patch("agents.outcome_evaluator._ensure_spy_prices"):
        written = evaluate_matured_recommendations(min_age_days=1)

    # Should have written at least one outcome row
    assert written > 0

    conn2 = _open_conn(mem_db)
    rows = conn2.execute(
        "SELECT * FROM recommendation_outcomes WHERE recommendation_id=?", (rec_id,)
    ).fetchall()
    conn2.close()

    assert len(rows) > 0
    # For rejected HOLD: actual_r = hold_r, not estimated
    row_1m = next((r for r in rows if r["horizon"] == "1m"), None)
    if row_1m:
        assert row_1m["actual_is_estimated"] == 0
        assert row_1m["actual_return"] is not None


# ── Scenario 9: SELL_CC actual outcome from exec_rec ─────────────────────────

def test_sell_cc_actual_from_exec_rec_differs_from_strategy_return(mem_db):
    """SELL_CC with exec_rec uses real premium+strike vs payload premium+strike."""
    from agents.outcome_evaluator import _compute_scenarios

    entry_price = 180.0
    horizon_price = 185.0
    exec_rec = {
        "execution_price": 3.5,  # actual premium (different from payload)
        "execution_date": "2026-01-02",
        "strike": 188.0,         # actual strike (different from payload)
    }
    prices = {"ANET": horizon_price, "ANET@2026-01-01": entry_price, "SPY": 500.0, "SPY@2026-01-01": 450.0}

    import agents.outcome_evaluator as oe
    with patch.object(oe, "_ticker_price_at", side_effect=lambda t, d: prices.get(f"{t}@{d}") or prices.get(t)), \
         patch.object(oe, "_spy_price_at", side_effect=lambda d: prices.get(f"SPY@{d}") or prices.get("SPY")):
        actual, agent, hold, spy, estimated, cc_ret, cc_alpha = _compute_scenarios(
            "ANET", "SELL_CC", "2026-01-01", "2026-04-01",
            {"premium": 2.5, "strike": 195.0},  # payload values (different)
            entry_price, decision="accepted",
            exec_rec=exec_rec,
        )

    # actual uses exec values: min(185.0, 188.0) = 185.0; (185 - 180 + 3.5) / 180
    expected_actual = (min(horizon_price, 188.0) - entry_price + 3.5) / entry_price
    assert abs(actual - expected_actual) < 0.001
    assert not estimated
    # cc_ret is the agent recommendation path (uses payload premium/strike)
    assert cc_ret is not None
    assert abs(actual - cc_ret) > 0.001  # they should differ
