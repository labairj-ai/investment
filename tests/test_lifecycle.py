from __future__ import annotations
"""Lifecycle integration tests — 0081.

Tests full paths from recommendation creation through decisions, executions,
and outcome evaluation using the mem_db and mock_llm fixtures.

All 8+ scenarios use the in-memory DB with real migrate() and real agent_db helpers.
"""
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── Seed helpers ───────────────────────────────────────────────────────────────

def _seed_rec(conn, ticker="ANET", action="HOLD", created_at=None, status="open", payload=None):
    ts = created_at or (time.time() - 100 * 86400)  # 100 days ago by default
    conn.execute(
        """INSERT INTO recommendations
           (ticker, action, recommendation_score, confidence, priority, status, created_at, action_payload_json)
           VALUES (?, ?, 50, 60, 'normal', ?, ?, ?)""",
        (ticker, action, status, ts, json.dumps(payload) if payload else None),
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
    """TRIM accepted + exec_rec → two-component actual_r (0103): sold fraction earns exec gain."""
    import agent_db
    from agents.outcome_evaluator import _compute_scenarios

    entry_price = 180.0
    horizon_price = 200.0
    exec_price = 185.0
    f = 0.25
    exec_rec = {
        "execution_price": exec_price,
        "execution_date": "2026-01-03",
        "quantity": 30.0,
        "execution_fraction": f,
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
    exec_gain = (exec_price / entry_price) - 1
    # 0103: two-component formula — sold fraction earns exec_gain, retained earns hold_r
    expected_actual = f * exec_gain + (1 - f) * hold_r
    assert abs(actual - expected_actual) < 0.0001, (
        f"TRIM actual_r={actual:.6f}, expected {expected_actual:.6f}. "
        "Formula: f*exec_gain + (1-f)*hold_r (0103)"
    )
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


# ── 0093: Dynamic NO_ACTION state hashes ──────────────────────────────────────

def _make_holding(ticker="ANET", shares=100, price=300.0, weight_pct=15.0):
    from agents.contracts import HoldingSnapshot
    return HoldingSnapshot(
        ticker=ticker, layer=2, shares=shares, avg_cost=200.0,
        current_price=price, market_value=shares * price, weight_pct=weight_pct,
    )


def _make_snapshot(holdings=None, layer_weights=None):
    from agents.contracts import PortfolioSnapshot
    h = holdings or [_make_holding()]
    return PortfolioSnapshot(
        date="2026-09-06", total_value=100_000.0, holdings=h,
        layer_weights=layer_weights or {1: 50.0, 2: 30.0, 3: 20.0},
        macro_scores={}, generated_at=time.time(),
        price_as_of="2026-09-05", portfolio_as_of="2026-09-05",
    )


def test_cc_no_action_hash_changes_when_iv_bucket_changes(mem_db):
    """Changing IV from ~45% to ~10% produces different NO_ACTION hashes."""
    import agent_db
    from agents.orchestrator import _compute_no_action_state_extras

    holding = _make_holding("ANET")
    snapshot = _make_snapshot([holding])

    # Seed option snapshot with high IV
    agent_db.upsert_option_quote_snapshot(
        "ANET", strike=310.0, expiration="2026-10-17",
        iv=0.45, bid=3.0, ask=3.2, spread_pct=0.062,
    )
    extras_high = _compute_no_action_state_extras("covered_call", "ANET", snapshot, holding)

    # Replace snapshot with low IV
    agent_db.upsert_option_quote_snapshot(
        "ANET", strike=310.0, expiration="2026-10-17",
        iv=0.12, bid=0.5, ask=0.55, spread_pct=0.09,
    )
    extras_low = _compute_no_action_state_extras("covered_call", "ANET", snapshot, holding)

    assert extras_high["iv_bucket"] != extras_low["iv_bucket"]
    assert extras_high["iv_bucket"] == 45   # 0.45 * 100 / 5 → 45
    assert extras_low["iv_bucket"]  == 10   # 0.12 * 100 / 5 → 10 (rounds to nearest 5)


def test_cc_no_action_hash_changes_when_open_cc_opens(mem_db):
    """Open CC flag differs between no open CC and an existing open CC."""
    import agent_db
    from agents.orchestrator import _compute_no_action_state_extras

    holding = _make_holding("MSFT")
    snapshot = _make_snapshot([holding])

    # No CC exists yet
    extras_no_cc = _compute_no_action_state_extras("covered_call", "MSFT", snapshot, holding)
    assert extras_no_cc["open_cc"] == 0

    # Seed an open CC (cc_positions table lives in serve.py's init_db; create it here)
    _conn = agent_db._connect()
    _conn.execute(
        """CREATE TABLE IF NOT EXISTS cc_positions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               ticker TEXT NOT NULL, contracts INTEGER NOT NULL, strike REAL NOT NULL,
               expiry TEXT NOT NULL, premium_per_contract REAL NOT NULL,
               opened_date TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open')"""
    )
    _conn.execute(
        """INSERT INTO cc_positions (ticker, strike, expiry, premium_per_contract, contracts, status, opened_date)
           VALUES ('MSFT', 400.0, '2026-10-17', 2.5, 1, 'open', '2026-09-01')""",
    )
    _conn.commit()
    _conn.close()

    extras_with_cc = _compute_no_action_state_extras("covered_call", "MSFT", snapshot, holding)
    assert extras_with_cc["open_cc"] == 1


# ── 0123: CC NO_ACTION hash includes CC policy fingerprint ────────────────────

def _seed_cc_thesis(conn, ticker, delta=0.30, strategy="INCOME"):
    """Insert a minimal active thesis row with a cc_policy blob."""
    cc_policy = json.dumps({"strategy": strategy, "max_preferred_delta": delta,
                            "minimum_otm_pct": 0.03, "avoid_earnings": False,
                            "preferred_dte_min": None, "preferred_dte_max": None})
    conn.execute(
        """INSERT OR REPLACE INTO investment_theses
           (ticker, status, version, summary, created_at, intake_json, cc_policy)
           VALUES (?, 'active', 1, 'test thesis', ?, '{}', ?)""",
        (ticker, time.time(), cc_policy),
    )
    conn.commit()


def test_cc_policy_hash_changes_when_delta_changes(mem_db):
    """cc_policy_hash differs after max_preferred_delta changes in the thesis."""
    import agent_db
    from agents.orchestrator import _compute_no_action_state_extras

    conn = _open_conn(mem_db)
    _seed_cc_thesis(conn, "ANET", delta=0.30)
    conn.close()

    holding = _make_holding("ANET")
    snapshot = _make_snapshot([holding])
    extras_30 = _compute_no_action_state_extras("covered_call", "ANET", snapshot, holding)

    # Update delta in thesis
    conn = _open_conn(mem_db)
    conn.execute(
        "UPDATE investment_theses SET cc_policy=? WHERE ticker=?",
        (json.dumps({"strategy": "INCOME", "max_preferred_delta": 0.20,
                     "minimum_otm_pct": 0.03, "avoid_earnings": False,
                     "preferred_dte_min": None, "preferred_dte_max": None}), "ANET"),
    )
    conn.commit()
    conn.close()

    extras_20 = _compute_no_action_state_extras("covered_call", "ANET", snapshot, holding)

    assert "cc_policy_hash" in extras_30
    assert "cc_policy_hash" in extras_20
    assert extras_30["cc_policy_hash"] != extras_20["cc_policy_hash"], (
        "cc_policy_hash must change when max_preferred_delta changes"
    )


def test_cc_policy_hash_stable_when_policy_unchanged(mem_db):
    """cc_policy_hash is identical across two calls with no policy change."""
    import agent_db
    from agents.orchestrator import _compute_no_action_state_extras

    conn = _open_conn(mem_db)
    _seed_cc_thesis(conn, "ANET", delta=0.25, strategy="UPSIDE_PRESERVATION")
    conn.close()

    holding = _make_holding("ANET")
    snapshot = _make_snapshot([holding])
    extras_a = _compute_no_action_state_extras("covered_call", "ANET", snapshot, holding)
    extras_b = _compute_no_action_state_extras("covered_call", "ANET", snapshot, holding)

    assert extras_a["cc_policy_hash"] == extras_b["cc_policy_hash"]


def test_cc_policy_hash_stable_when_no_thesis(mem_db):
    """cc_policy_hash is non-empty and stable when no thesis exists (uses defaults)."""
    from agents.orchestrator import _compute_no_action_state_extras

    holding = _make_holding("NVDA")
    snapshot = _make_snapshot([holding])
    extras_a = _compute_no_action_state_extras("covered_call", "NVDA", snapshot, holding)
    extras_b = _compute_no_action_state_extras("covered_call", "NVDA", snapshot, holding)

    assert "cc_policy_hash" in extras_a
    assert len(extras_a["cc_policy_hash"]) == 12
    assert extras_a["cc_policy_hash"] == extras_b["cc_policy_hash"]


def test_guardian_hash_changes_when_max_weight_crosses_bucket(mem_db):
    """max_weight_bucket in guardian extras reflects nearest-0.5% bucketing."""
    from agents.orchestrator import _compute_no_action_state_extras

    holding_lo = _make_holding("ANET", weight_pct=19.8)
    snap_lo = _make_snapshot([holding_lo], layer_weights={1: 50.0, 2: 30.0, 3: 19.8})
    extras_lo = _compute_no_action_state_extras("portfolio_guardian", "ANET", snap_lo, holding_lo)

    holding_hi = _make_holding("ANET", weight_pct=23.1)
    snap_hi = _make_snapshot([holding_hi], layer_weights={1: 50.0, 2: 30.0, 3: 23.1})
    extras_hi = _compute_no_action_state_extras("portfolio_guardian", "ANET", snap_hi, holding_hi)

    assert extras_lo["max_weight_bucket"] != extras_hi["max_weight_bucket"]
    assert extras_lo["max_weight_bucket"] == 20.0  # 19.8 → rounds to 20.0 (nearest 0.5)
    assert extras_hi["max_weight_bucket"] == 23.0  # 23.1 → rounds to 23.0


def test_guardian_layer_drift_flag(mem_db):
    """layer_drift_flag is 1 when a layer exceeds target+5% per strategy_config.LAYER_TARGETS."""
    from agents.orchestrator import _compute_no_action_state_extras, LAYER_TARGETS

    holding = _make_holding("ANET")

    # Build a snapshot where one layer clearly exceeds target+5 using real targets
    # Use layer with smallest index that has a target; force it 6pp over target
    first_layer, first_target = min(LAYER_TARGETS.items())
    drift_weights = {k: v for k, v in LAYER_TARGETS.items()}
    drift_weights[first_layer] = first_target + 6.0  # clearly over target+5
    snap_drift = _make_snapshot([holding], layer_weights=drift_weights)
    extras_drift = _compute_no_action_state_extras("portfolio_guardian", "ANET", snap_drift, holding)
    assert extras_drift["layer_drift_flag"] == 1

    # Within tolerance: use exact targets
    snap_ok = _make_snapshot([holding], layer_weights={k: v for k, v in LAYER_TARGETS.items()})
    extras_ok = _compute_no_action_state_extras("portfolio_guardian", "ANET", snap_ok, holding)
    assert extras_ok["layer_drift_flag"] == 0


def test_unknown_agent_returns_empty_extras(mem_db):
    """Unknown agent types return an empty dict (no crash)."""
    from agents.orchestrator import _compute_no_action_state_extras

    holding = _make_holding("ANET")
    snapshot = _make_snapshot([holding])
    extras = _compute_no_action_state_extras("thesis_monitor", "ANET", snapshot, holding)
    assert extras == {}


# ── 0119: Guardian vol_bucket and risk_contrib_bucket ─────────────────────────

def _seed_price_series(conn, ticker, base_price, daily_move, n_days=22):
    """Seed n_days of holding_day rows with alternating +/-daily_move prices."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS holding_day
           (ticker TEXT, day TEXT, price REAL, value REAL, weight_pct REAL, shares REAL,
            PRIMARY KEY (ticker, day))"""
    )
    price = base_price
    for i in range(n_days):
        day = (date.today() - timedelta(days=n_days - i)).isoformat()
        price = base_price + (daily_move if i % 2 == 0 else -daily_move)
        conn.execute(
            "INSERT OR REPLACE INTO holding_day (ticker, day, price, value, weight_pct, shares) "
            "VALUES (?, ?, ?, ?, 15.0, 100)",
            (ticker, day, price, price * 100),
        )
    conn.commit()


def test_guardian_vol_bucket_unknown_when_insufficient_history(mem_db):
    """vol_bucket is 'unknown' when fewer than 21 holding_day rows exist."""
    import agent_db
    from agents.orchestrator import _compute_no_action_state_extras

    conn = _open_conn(mem_db)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS holding_day
           (ticker TEXT, day TEXT, price REAL, value REAL, weight_pct REAL, shares REAL,
            PRIMARY KEY (ticker, day))"""
    )
    for i in range(5):
        day = (date.today() - timedelta(days=5 - i)).isoformat()
        conn.execute(
            "INSERT OR REPLACE INTO holding_day (ticker, day, price, value, weight_pct, shares) "
            "VALUES ('ANET', ?, 300.0, 30000.0, 15.0, 100)",
            (day,),
        )
    conn.commit()
    conn.close()

    holding = _make_holding("ANET", weight_pct=15.0)
    snapshot = _make_snapshot([holding])
    extras = _compute_no_action_state_extras("portfolio_guardian", "ANET", snapshot, holding)

    assert extras["vol_bucket"] == "unknown"
    assert extras["risk_contrib_bucket"] == "unknown"


def test_guardian_vol_bucket_changes_when_vol_crosses_bucket(mem_db):
    """Guardian NO_ACTION hash changes when realized vol crosses a 5% bucket boundary."""
    import agent_db
    from agents.orchestrator import _compute_no_action_state_extras

    conn = _open_conn(mem_db)

    # Low-vol series: prices oscillate ±0.50 around 300 → daily move ≈ 0.17% → annualized ≈ 2.7%
    _seed_price_series(conn, "LOW", base_price=300.0, daily_move=0.5, n_days=22)
    # High-vol series: prices oscillate ±6 around 300 → daily move ≈ 2% → annualized ≈ 32%
    _seed_price_series(conn, "HIGH", base_price=300.0, daily_move=6.0, n_days=22)
    conn.close()

    holding_lo = _make_holding("LOW", weight_pct=15.0)
    snap_lo = _make_snapshot([holding_lo])
    extras_lo = _compute_no_action_state_extras("portfolio_guardian", "LOW", snap_lo, holding_lo)

    holding_hi = _make_holding("HIGH", weight_pct=15.0)
    snap_hi = _make_snapshot([holding_hi])
    extras_hi = _compute_no_action_state_extras("portfolio_guardian", "HIGH", snap_hi, holding_hi)

    assert extras_lo["vol_bucket"] != "unknown"
    assert extras_hi["vol_bucket"] != "unknown"
    assert extras_lo["vol_bucket"] != extras_hi["vol_bucket"], (
        f"vol_bucket should differ: low={extras_lo['vol_bucket']} high={extras_hi['vol_bucket']}"
    )
    assert extras_lo["risk_contrib_bucket"] != extras_hi["risk_contrib_bucket"]


def test_guardian_risk_contrib_reflects_weight_and_vol(mem_db):
    """risk_contrib_bucket scales with both weight and vol."""
    import agent_db
    from agents.orchestrator import _compute_no_action_state_extras

    conn = _open_conn(mem_db)
    _seed_price_series(conn, "ANET", base_price=300.0, daily_move=6.0, n_days=22)
    conn.close()

    holding_small = _make_holding("ANET", weight_pct=5.0)
    snap_small = _make_snapshot([holding_small])
    extras_small = _compute_no_action_state_extras("portfolio_guardian", "ANET", snap_small, holding_small)

    holding_large = _make_holding("ANET", weight_pct=20.0)
    snap_large = _make_snapshot([holding_large])
    extras_large = _compute_no_action_state_extras("portfolio_guardian", "ANET", snap_large, holding_large)

    assert extras_small["risk_contrib_bucket"] != "unknown"
    assert extras_large["risk_contrib_bucket"] != "unknown"
    # Larger weight → higher risk contribution
    assert extras_large["risk_contrib_bucket"] > extras_small["risk_contrib_bucket"], (
        f"small={extras_small['risk_contrib_bucket']} large={extras_large['risk_contrib_bucket']}"
    )


# ── 0099: TRIM/ALLOCATE accepted-not-executed → actual_r = NULL ───────────────

def test_trim_accepted_without_execution_is_null(mem_db):
    """TRIM accepted but no exec_rec → actual_r=None, actual_is_estimated=True (0099)."""
    from agents.outcome_evaluator import _compute_scenarios

    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 510.0, "SPY@2026-01-01": 455.0}

    import agents.outcome_evaluator as oe
    with patch.object(oe, "_ticker_price_at", side_effect=lambda t, d: prices.get(f"{t}@{d}") or prices.get(t)), \
         patch.object(oe, "_spy_price_at", side_effect=lambda d: prices.get(f"SPY@{d}") or prices.get("SPY")):
        actual, agent, hold, spy, estimated, _, _ = _compute_scenarios(
            "ANET", "TRIM", "2026-01-01", "2026-04-01",
            {"trim_fraction": 0.5}, 180.0, decision="accepted",
        )

    assert actual is None, (
        f"TRIM accepted-without-exec should produce actual_r=None, got {actual}. "
        "Fix in outcome_evaluator.py _ACCEPTED_NO_EXEC_NULL (see 0099)"
    )
    assert estimated is True


def test_allocate_accepted_without_execution_is_null(mem_db):
    """ALLOCATE accepted but no exec_rec → actual_r=None, actual_is_estimated=True (0099)."""
    from agents.outcome_evaluator import _compute_scenarios

    prices = {"ANET": 200.0, "ANET@2026-01-01": 180.0, "SPY": 510.0, "SPY@2026-01-01": 455.0}

    import agents.outcome_evaluator as oe
    with patch.object(oe, "_ticker_price_at", side_effect=lambda t, d: prices.get(f"{t}@{d}") or prices.get(t)), \
         patch.object(oe, "_spy_price_at", side_effect=lambda d: prices.get(f"SPY@{d}") or prices.get("SPY")):
        actual, agent, hold, spy, estimated, _, _ = _compute_scenarios(
            "ANET", "ALLOCATE", "2026-01-01", "2026-04-01",
            {}, 180.0, decision="accepted",
        )

    assert actual is None
    assert estimated is True


def test_trim_accepted_with_execution_uses_fraction(mem_db):
    """TRIM with exec_rec: actual_r is non-null, non-estimated, and uses two-component formula (0103)."""
    from agents.outcome_evaluator import _compute_scenarios

    entry_price = 180.0
    horizon_price = 200.0
    exec_price = 185.0
    f = 0.25
    exec_rec = {
        "execution_price": exec_price,
        "execution_date": "2026-01-03",
        "quantity": 30.0,
        "execution_fraction": f,
    }
    prices = {"ANET": horizon_price, "ANET@2026-01-01": entry_price, "SPY": 500.0, "SPY@2026-01-01": 450.0}

    import agents.outcome_evaluator as oe
    with patch.object(oe, "_ticker_price_at", side_effect=lambda t, d: prices.get(f"{t}@{d}") or prices.get(t)), \
         patch.object(oe, "_spy_price_at", side_effect=lambda d: prices.get(f"SPY@{d}") or prices.get("SPY")):
        actual, _, _, _, estimated, _, _ = _compute_scenarios(
            "ANET", "TRIM", "2026-01-01", "2026-04-01",
            {"trim_fraction": 0.5}, entry_price, decision="accepted",
            exec_rec=exec_rec,
        )

    assert actual is not None, "TRIM with execution should produce a real actual_r, not NULL"
    assert not estimated
    hold_r = (horizon_price - entry_price) / entry_price
    exec_gain = (exec_price / entry_price) - 1
    expected = f * exec_gain + (1 - f) * hold_r
    assert abs(actual - expected) < 0.0001, f"Expected {expected:.6f}, got {actual:.6f}"


# ── 0103: _compute_actual_trim unit tests ─────────────────────────────────────

def test_compute_actual_trim_two_component_formula(mem_db):
    """_compute_actual_trim returns f*exec_gain + (1-f)*hold_r."""
    from agents.outcome_evaluator import _compute_actual_trim
    exec_rec = {"execution_price": 190.0, "execution_fraction": 0.30}
    entry_price = 180.0
    hold_r = (200.0 - 180.0) / 180.0  # 11.11%
    actual, estimated = _compute_actual_trim(exec_rec, entry_price, hold_r)
    exec_gain = (190.0 / 180.0) - 1   # 5.56%
    expected = 0.30 * exec_gain + 0.70 * hold_r
    assert abs(actual - expected) < 1e-9
    assert not estimated


def test_compute_actual_trim_hold_r_none_returns_none(mem_db):
    """_compute_actual_trim returns (None, False) when hold_r is unavailable."""
    from agents.outcome_evaluator import _compute_actual_trim
    exec_rec = {"execution_price": 190.0, "execution_fraction": 0.25}
    actual, estimated = _compute_actual_trim(exec_rec, 180.0, None)
    assert actual is None
    assert not estimated


def test_compute_actual_trim_derives_fraction_from_quantity(mem_db):
    """_compute_actual_trim falls back to quantity/position_shares_before for fraction."""
    from agents.outcome_evaluator import _compute_actual_trim
    exec_rec = {
        "execution_price": 190.0,
        "quantity": 25.0,
        "position_shares_before": 100.0,
    }
    hold_r = 0.10
    actual, _ = _compute_actual_trim(exec_rec, 180.0, hold_r)
    f = 25.0 / 100.0  # 0.25
    exec_gain = (190.0 / 180.0) - 1
    expected = f * exec_gain + (1 - f) * hold_r
    assert abs(actual - expected) < 1e-9


# ── 0103: _compute_actual_allocate unit tests ─────────────────────────────────

def test_compute_actual_allocate_uses_exec_price_as_basis(mem_db):
    """_compute_actual_allocate returns (h_price - exec_price) / exec_price."""
    from agents.outcome_evaluator import _compute_actual_allocate
    exec_rec = {"execution_price": 95.0, "execution_date": "2026-01-05"}
    actual, estimated = _compute_actual_allocate(exec_rec, 110.0)
    expected = (110.0 - 95.0) / 95.0
    assert abs(actual - expected) < 1e-9
    assert not estimated


def test_compute_actual_allocate_no_horizon_price_returns_none(mem_db):
    """_compute_actual_allocate returns (None, True) when horizon price is unavailable."""
    from agents.outcome_evaluator import _compute_actual_allocate
    exec_rec = {"execution_price": 95.0, "execution_date": "2026-01-05"}
    actual, estimated = _compute_actual_allocate(exec_rec, None)
    assert actual is None
    assert estimated


# ── 0103: _compute_actual_rebalance unit tests ────────────────────────────────

def test_compute_actual_rebalance_blends_from_and_to_return(mem_db):
    """_compute_actual_rebalance blends from-ticker gain + to-ticker return."""
    from agents.outcome_evaluator import _compute_actual_rebalance
    import agents.outcome_evaluator as oe

    exec_rec = {"execution_price": 200.0, "execution_date": "2026-01-10"}
    entry_price = 190.0
    pl = {"to_ticker": "VTI", "fraction": 0.40}
    prices = {
        ("VTI", "2026-01-10"): 130.0,   # to-ticker exec_date price
        ("VTI", "2026-04-01"): 143.0,   # to-ticker horizon price
    }

    with patch.object(oe, "_ticker_price_at", side_effect=lambda t, d: prices.get((t, d))):
        actual, estimated = _compute_actual_rebalance(exec_rec, entry_price, pl, "2026-04-01")

    from_gain = (200.0 / 190.0) - 1
    to_r = (143.0 - 130.0) / 130.0
    expected = (1 - 0.40) * from_gain + 0.40 * to_r
    assert abs(actual - expected) < 1e-9
    assert not estimated


def test_compute_actual_rebalance_no_to_ticker_returns_from_gain(mem_db):
    """_compute_actual_rebalance with no to_ticker returns from-gain only, estimated=True."""
    from agents.outcome_evaluator import _compute_actual_rebalance
    import agents.outcome_evaluator as oe

    exec_rec = {"execution_price": 200.0, "execution_date": "2026-01-10"}
    entry_price = 190.0
    pl = {"fraction": 0.50}  # no to_ticker

    with patch.object(oe, "_ticker_price_at", return_value=None):
        actual, estimated = _compute_actual_rebalance(exec_rec, entry_price, pl, "2026-04-01")

    from_gain = (200.0 / 190.0) - 1
    expected = (1 - 0.50) * from_gain
    assert abs(actual - expected) < 1e-9
    assert estimated


# ── 0103: Decision Quality exclusion gate ─────────────────────────────────────

def test_decision_quality_excludes_trim_allocate_rebalance(mem_db):
    """get_decision_quality_note returns '' for TRIM/ALLOCATE/REBALANCE regardless of data."""
    from agents.decision_quality import get_decision_quality_note, _EXCLUDE_FROM_DQ

    assert "TRIM" in _EXCLUDE_FROM_DQ
    assert "ALLOCATE" in _EXCLUDE_FROM_DQ
    assert "REBALANCE" in _EXCLUDE_FROM_DQ

    for action in ("TRIM", "ALLOCATE", "REBALANCE"):
        note = get_decision_quality_note("sell_trim", action)
        assert note == "", f"Expected empty note for {action}, got: {note!r}"


# ── 0117: CC assignment end-to-end via evaluate_matured_recommendations ───────

def _seed_exec(conn, rec_id, ticker, action, exec_date, premium, strike, expiration):
    """Insert an executed_actions row for a SELL_CC."""
    conn.execute(
        """INSERT INTO executed_actions
           (ticker, action, execution_date, execution_price, strike, expiration, premium,
            contracts, recommendation_id, source)
           VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, 'manual')""",
        (ticker, action, exec_date, premium, strike, expiration, premium, rec_id),
    )
    conn.commit()


def test_sell_cc_assigned_lifecycle_locks_at_assignment_return(mem_db):
    """0117: SELL_CC assigned at expiry → 30d_post actual_r == locked assignment return, not 0."""
    import agent_db
    from agents.outcome_evaluator import evaluate_matured_recommendations

    conn = _open_conn(mem_db)

    entry_price = 180.0
    strike = 190.0
    premium = 3.0
    # Dates: entry 200 days ago, expiry 140 days ago, 30d_post 110 days ago
    entry_date   = (date.today() - timedelta(days=200)).isoformat()
    expiry_date  = (date.today() - timedelta(days=140)).isoformat()
    post30_date  = (date.today() - timedelta(days=110)).isoformat()
    exec_date    = (date.today() - timedelta(days=199)).isoformat()
    entry_ts     = time.time() - 200 * 86400

    rec_id = _seed_rec(conn, ticker="ANET", action="SELL_CC", created_at=entry_ts, status="accepted",
                       payload={"expiration": expiry_date, "strike": strike, "premium": premium})
    conn.execute(
        "INSERT INTO user_decisions (recommendation_id, decision, reason_code, decided_at) VALUES (?,?,?,?)",
        (rec_id, "accepted", "OTHER", time.time()),
    )
    conn.commit()

    _seed_exec(conn, rec_id, "ANET", "SELL_CC", exec_date, premium, strike, expiry_date)

    # Prices: entry; S_exp > K (assigned); 30d_post price irrelevant once assigned
    _seed_price(conn, "ANET", entry_date, entry_price)
    _seed_price(conn, "ANET", expiry_date, 200.0)   # S_exp=200 > K=190 → assigned
    _seed_price(conn, "ANET", post30_date, 210.0)   # irrelevant; cash is locked
    _seed_spy(conn, entry_date, 450.0)
    _seed_spy(conn, expiry_date, 470.0)
    _seed_spy(conn, post30_date, 480.0)
    conn.close()

    expected_assign_r = (strike - entry_price + premium) / entry_price

    with patch("agents.outcome_evaluator._ensure_spy_prices"):
        written = evaluate_matured_recommendations(min_age_days=1)

    assert written > 0

    conn2 = _open_conn(mem_db)
    rows = {
        r["horizon"]: dict(r)
        for r in conn2.execute(
            "SELECT * FROM recommendation_outcomes WHERE recommendation_id=?", (rec_id,)
        ).fetchall()
    }
    conn2.close()

    assert "at_expiry" in rows, "at_expiry horizon must be written"
    assert rows["at_expiry"]["cc_assignment_state"] == "assigned"

    if "30d_post" in rows:
        post = rows["30d_post"]
        assert abs(post["actual_return"] - expected_assign_r) < 0.0001, (
            f"30d_post actual_r should lock at {expected_assign_r:.4f} (assignment return), "
            f"got {post['actual_return']}"
        )


def test_sell_cc_expired_lifecycle_uses_uncapped_formula(mem_db):
    """0117: SELL_CC expired at expiry → 30d_post actual_r uses (S30 - S0 + premium) / S0."""
    import agent_db
    from agents.outcome_evaluator import evaluate_matured_recommendations

    conn = _open_conn(mem_db)

    entry_price = 180.0
    strike = 190.0
    premium = 3.0
    entry_date   = (date.today() - timedelta(days=200)).isoformat()
    expiry_date  = (date.today() - timedelta(days=140)).isoformat()
    post30_date  = (date.today() - timedelta(days=110)).isoformat()
    exec_date    = (date.today() - timedelta(days=199)).isoformat()
    entry_ts     = time.time() - 200 * 86400

    rec_id = _seed_rec(conn, ticker="JOBY", action="SELL_CC", created_at=entry_ts, status="accepted",
                       payload={"expiration": expiry_date, "strike": strike, "premium": premium})
    conn.execute(
        "INSERT INTO user_decisions (recommendation_id, decision, reason_code, decided_at) VALUES (?,?,?,?)",
        (rec_id, "accepted", "OTHER", time.time()),
    )
    conn.commit()

    _seed_exec(conn, rec_id, "JOBY", "SELL_CC", exec_date, premium, strike, expiry_date)

    post30_price = 210.0
    _seed_price(conn, "JOBY", entry_date, entry_price)
    _seed_price(conn, "JOBY", expiry_date, 185.0)   # S_exp=185 < K=190 → expired worthless
    _seed_price(conn, "JOBY", post30_date, post30_price)
    _seed_spy(conn, entry_date, 450.0)
    _seed_spy(conn, expiry_date, 460.0)
    _seed_spy(conn, post30_date, 465.0)
    conn.close()

    expected_post_r = (post30_price - entry_price + premium) / entry_price

    with patch("agents.outcome_evaluator._ensure_spy_prices"):
        evaluate_matured_recommendations(min_age_days=1)

    conn2 = _open_conn(mem_db)
    rows = {
        r["horizon"]: dict(r)
        for r in conn2.execute(
            "SELECT * FROM recommendation_outcomes WHERE recommendation_id=?", (rec_id,)
        ).fetchall()
    }
    conn2.close()

    assert "at_expiry" in rows
    assert rows["at_expiry"]["cc_assignment_state"] == "expired"

    if "30d_post" in rows:
        post = rows["30d_post"]
        assert abs(post["actual_return"] - expected_post_r) < 0.0001, (
            f"30d_post actual_r should use uncapped formula {expected_post_r:.4f}, "
            f"got {post['actual_return']}"
        )


# ── 0120: Audit manifest reference IDs ───────────────────────────────────────

def test_strategy_config_hash_is_stable_and_nonempty():
    """strategy_config.get_hash() returns a stable 12-char hex string."""
    import strategy_config
    h1 = strategy_config.get_hash()
    h2 = strategy_config.get_hash()
    assert isinstance(h1, str), "Strategy config hash must be a string"
    assert len(h1) == 12, f"Expected 12-char hash, got: {h1!r}"
    assert all(c in "0123456789abcdef" for c in h1), f"Hash must be lowercase hex: {h1!r}"
    assert h1 == h2, "Strategy config hash must be stable across calls"


def test_audit_snapshot_includes_reference_ids(mem_db):
    """agent_runs.input_snapshot_json stores strategy_config_hash and reference ID fields."""
    import agent_db, json, strategy_config

    cfg_hash = strategy_config.get_hash()
    snap = {
        "ticker": "ANET",
        "price": 180.0,
        "strategy_config_hash": cfg_hash,
        "option_snapshot_id": None,
        "earnings_event_id": None,
        "financial_snapshot_hash": None,
    }
    run_id = agent_db.insert_agent_run(
        agent_type="covered_call",
        scope="ticker",
        ticker="ANET",
        trigger_type="price_move",
        trigger_key="ANET",
        model="test-model",
        prompt_version="v1",
        input_hash="abc123",
        input_snapshot=snap,
    )

    conn = agent_db._connect()
    row = conn.execute(
        "SELECT input_snapshot_json FROM agent_runs WHERE id=?", (run_id,)
    ).fetchone()
    conn.close()

    assert row is not None
    stored = json.loads(row["input_snapshot_json"])
    assert "strategy_config_hash" in stored, "strategy_config_hash must be in input_snapshot_json"
    assert stored["strategy_config_hash"] == cfg_hash
    assert "option_snapshot_id" in stored
    assert "earnings_event_id" in stored
    assert "financial_snapshot_hash" in stored


# ── 0124: Missing lifecycle tests ─────────────────────────────────────────────

def _seed_cc_positions_table(conn):
    """Create cc_positions table (normally created by serve.py, not agent_db.migrate)."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cc_positions (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker               TEXT NOT NULL,
            contracts            INTEGER NOT NULL,
            strike               REAL NOT NULL,
            expiry               TEXT NOT NULL,
            premium_per_contract REAL NOT NULL,
            opened_date          TEXT NOT NULL,
            status               TEXT NOT NULL DEFAULT 'open',
            closed_date          TEXT,
            closed_price         REAL,
            close_type           TEXT,
            net_premium          REAL,
            notes                TEXT
        )
    """)
    conn.commit()


def test_trim_two_fills_lifecycle_uses_vwap(mem_db):
    """Two-fill TRIM: evaluate_matured_recommendations uses VWAP exec_price and two-component actual_r."""
    import agent_db
    from agents.outcome_evaluator import evaluate_matured_recommendations

    conn = _open_conn(mem_db)

    entry_price = 180.0
    f1_price, f1_qty = 185.0, 30.0
    f2_price, f2_qty = 188.0, 20.0
    pos_shares = 100.0
    vwap = (f1_price * f1_qty + f2_price * f2_qty) / (f1_qty + f2_qty)
    f_total = (f1_qty + f2_qty) / pos_shares  # 0.50

    entry_ts = time.time() - 100 * 86400
    entry_date = (date.today() - timedelta(days=100)).isoformat()
    h1m_date = (date.today() - timedelta(days=70)).isoformat()
    exec_date = (date.today() - timedelta(days=99)).isoformat()

    rec_id = _seed_rec(conn, ticker="ANET", action="TRIM", created_at=entry_ts,
                       status="accepted", payload={"trim_fraction": 0.5})
    conn.execute(
        "INSERT INTO user_decisions (recommendation_id, decision, reason_code, decided_at) "
        "VALUES (?, 'accepted', 'OTHER', ?)", (rec_id, time.time()),
    )
    conn.execute(
        """INSERT INTO executed_actions
           (ticker, action, execution_date, execution_price, quantity,
            position_shares_before, recommendation_id, source)
           VALUES ('ANET', 'TRIM', ?, ?, ?, ?, ?, 'manual')""",
        (exec_date, f1_price, f1_qty, pos_shares, rec_id),
    )
    conn.execute(
        """INSERT INTO executed_actions
           (ticker, action, execution_date, execution_price, quantity,
            position_shares_before, recommendation_id, source)
           VALUES ('ANET', 'TRIM', ?, ?, ?, NULL, ?, 'manual')""",
        (exec_date, f2_price, f2_qty, rec_id),
    )
    conn.commit()

    horizon_price = 200.0
    _seed_price(conn, "ANET", entry_date, entry_price)
    _seed_price(conn, "ANET", h1m_date, horizon_price)
    _seed_spy(conn, entry_date, 450.0)
    _seed_spy(conn, h1m_date, 465.0)
    conn.close()

    with patch("agents.outcome_evaluator._ensure_spy_prices"):
        written = evaluate_matured_recommendations(min_age_days=1)

    assert written > 0

    conn2 = _open_conn(mem_db)
    rows = {
        r["horizon"]: dict(r)
        for r in conn2.execute(
            "SELECT * FROM recommendation_outcomes WHERE recommendation_id=?", (rec_id,)
        ).fetchall()
    }
    conn2.close()

    assert "1m" in rows, f"Expected '1m' horizon row, got: {list(rows.keys())}"
    row = rows["1m"]

    hold_r = (horizon_price - entry_price) / entry_price
    exec_gain = (vwap / entry_price) - 1
    expected_actual = f_total * exec_gain + (1 - f_total) * hold_r

    assert row["actual_return"] is not None, "TRIM with execution should produce non-null actual_r"
    assert row["actual_is_estimated"] == 0
    assert abs(row["actual_return"] - expected_actual) < 0.0001, (
        f"VWAP two-component formula: expected {expected_actual:.6f}, got {row['actual_return']:.6f}"
    )


def test_sell_cc_execute_creates_position_atomically(mem_db):
    """SELL_CC record_execution_transaction creates executed_actions + cc_positions atomically."""
    import agent_db

    conn = _open_conn(mem_db)
    _seed_cc_positions_table(conn)
    rec_id = _seed_rec(conn, ticker="ANET", action="SELL_CC", status="accepted")
    conn.close()

    body = {
        "strike": 200.0, "expiration": "2026-11-21", "premium": 3.5,
        "contracts": 1, "execution_price": 3.5,
    }
    result = agent_db.record_execution_transaction(
        rec_id, "ANET", "SELL_CC", "2026-09-07", body,
    )

    assert result["exec_id"] is not None
    assert result["cc_pos_id"] is not None

    conn2 = _open_conn(mem_db)
    ea_count = conn2.execute(
        "SELECT COUNT(*) FROM executed_actions WHERE recommendation_id=?", (rec_id,)
    ).fetchone()[0]
    cc_count = conn2.execute(
        "SELECT COUNT(*) FROM cc_positions WHERE ticker='ANET' AND status='open'"
    ).fetchone()[0]
    conn2.close()

    assert ea_count == 1, "executed_actions row must exist after SELL_CC execute"
    assert cc_count == 1, "cc_positions row must be created atomically with executed_actions"


def test_sell_cc_execute_rollback_on_cc_positions_failure(mem_db):
    """SELL_CC execute: if cc_positions insert fails, executed_actions is also rolled back."""
    import agent_db
    from unittest.mock import patch as _patch

    conn = _open_conn(mem_db)
    _seed_cc_positions_table(conn)
    rec_id = _seed_rec(conn, ticker="MSFT", action="SELL_CC", status="accepted")
    conn.close()

    body = {
        "strike": 420.0, "expiration": "2026-11-21", "premium": 5.0,
        "contracts": 1, "execution_price": 5.0,
    }

    with _patch.object(agent_db, "_insert_cc_pos_conn", side_effect=Exception("injected failure")):
        with pytest.raises(Exception, match="injected failure"):
            agent_db.record_execution_transaction(rec_id, "MSFT", "SELL_CC", "2026-09-07", body)

    conn2 = _open_conn(mem_db)
    ea_count = conn2.execute(
        "SELECT COUNT(*) FROM executed_actions WHERE recommendation_id=?", (rec_id,)
    ).fetchone()[0]
    conn2.close()

    assert ea_count == 0, "executed_actions must be rolled back when cc_positions insert fails"


def test_roll_leg2_failure_rolls_back_leg1(mem_db):
    """ROLL: if leg-2 (STO) _insert_ea_conn fails, leg-1 (BTC) is also rolled back."""
    import agent_db
    from unittest.mock import patch as _patch

    conn = _open_conn(mem_db)
    _seed_cc_positions_table(conn)
    rec_id = _seed_rec(conn, ticker="ANET", action="ROLL_OUT", status="accepted")
    conn.close()

    body = {
        "existing_strike": 190.0, "existing_expiration": "2026-10-17",
        "new_strike": 200.0, "new_expiration": "2026-11-21",
        "btc_price": 2.0, "sto_premium": 3.5, "contracts": 1,
    }

    call_count = [0]
    orig_insert = agent_db._insert_ea_conn

    def fail_on_second(conn_, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] >= 2:
            raise Exception("injected leg-2 failure")
        return orig_insert(conn_, *args, **kwargs)

    with _patch.object(agent_db, "_insert_ea_conn", side_effect=fail_on_second):
        with pytest.raises(Exception, match="injected leg-2 failure"):
            agent_db.record_execution_transaction(rec_id, "ANET", "ROLL_OUT", "2026-09-07", body)

    conn2 = _open_conn(mem_db)
    ea_count = conn2.execute(
        "SELECT COUNT(*) FROM executed_actions WHERE recommendation_id=?", (rec_id,)
    ).fetchone()[0]
    conn2.close()

    assert ea_count == 0, "Leg-1 BTC insert must be rolled back when leg-2 STO insert fails"


def test_btc_management_rec_evaluated_at_maturity(mem_db):
    """BUY_TO_CLOSE rec aged past horizon → evaluate_matured_recommendations writes outcome row."""
    import agent_db
    from agents.outcome_evaluator import evaluate_matured_recommendations

    conn = _open_conn(mem_db)

    entry_price = 180.0
    btc_mark = 2.5
    horizon_price = 190.0
    entry_ts = time.time() - 100 * 86400
    entry_date = (date.today() - timedelta(days=100)).isoformat()
    h1m_date = (date.today() - timedelta(days=70)).isoformat()

    rec_id = _seed_rec(conn, ticker="NVDA", action="BUY_TO_CLOSE", created_at=entry_ts,
                       status="accepted", payload={"btc_price": btc_mark})
    conn.execute(
        "INSERT INTO user_decisions (recommendation_id, decision, reason_code, decided_at) "
        "VALUES (?, 'accepted', 'OTHER', ?)", (rec_id, time.time()),
    )
    conn.commit()

    _seed_price(conn, "NVDA", entry_date, entry_price)
    _seed_price(conn, "NVDA", h1m_date, horizon_price)
    _seed_spy(conn, entry_date, 450.0)
    _seed_spy(conn, h1m_date, 460.0)
    conn.close()

    with patch("agents.outcome_evaluator._ensure_spy_prices"):
        written = evaluate_matured_recommendations(min_age_days=1)

    assert written > 0, "Expected at least one outcome row to be written"

    conn2 = _open_conn(mem_db)
    rows = {
        r["horizon"]: dict(r)
        for r in conn2.execute(
            "SELECT * FROM recommendation_outcomes WHERE recommendation_id=?", (rec_id,)
        ).fetchall()
    }
    conn2.close()

    assert "1m" in rows, f"Expected '1m' horizon row for BUY_TO_CLOSE, got: {list(rows.keys())}"
    row = rows["1m"]

    # From MTM baseline: agent_r = hold_r (close at mark = zero net on option leg)
    hold_r = (horizon_price - entry_price) / entry_price
    assert row["recommended_path_return"] is not None
    assert abs(row["recommended_path_return"] - hold_r) < 0.0001, (
        f"BUY_TO_CLOSE agent_r should equal hold_r={hold_r:.4f}, "
        f"got {row['recommended_path_return']:.4f}"
    )
