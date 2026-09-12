"""Tests for the unified CC management engine (0151, 0152, 0157–0162, 0168–0173)."""
import sys
import sqlite3
from pathlib import Path
from datetime import date, timedelta

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from covered_call_rec import (
    ManagementPolicyContext,
    TaxFrictionDetail,
    evaluate_cc_management_state,
    evaluate_cc_roll_chain,
    _check_assignment_eligible,
    _lot_tax_friction,
)
import agent_db as _adb


# ── Helpers ───────────────────────────────────────────────────────────────────

def _ctx(**kwargs) -> ManagementPolicyContext:
    """Build a minimal context with sensible defaults; override with kwargs."""
    defaults = dict(
        ticker="TEST",
        current_price=155.0,
        strike=160.0,
        dte=30,
        delta=0.22,
        remaining_extrinsic=3.0,
        pct_captured=40.0,
        has_avoid=False,
        risk_events=[],
        contracts=1,
        assignment_price_floor=None,
        assignment_policy={},
        current_weight_pct=None,
        max_position_pct=None,
        conviction=None,
        thesis_health=None,
        assignment_tax_friction=0.0,
        tax_friction_reason="",
        tax_friction_available=True,
        tax_friction_detail=None,
        expiry_date=None,
    )
    defaults.update(kwargs)
    return ManagementPolicyContext(**defaults)


def _make_db(tmp_path, name="test.db"):
    """Create a temp SQLite DB with a cost_lots table."""
    db_path = tmp_path / name
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE cost_lots "
        "(id INTEGER PRIMARY KEY, ticker TEXT, shares REAL, cost_per_share REAL, purchase_date TEXT)"
    )
    conn.commit()
    conn.close()
    return db_path


def _patch_db(monkeypatch, db_path):
    """Monkeypatch agent_db._connect to use a temp DB."""
    def _connect():
        c = sqlite3.connect(str(db_path))
        c.row_factory = sqlite3.Row
        return c
    monkeypatch.setattr(_adb, "_connect", _connect)


def _insert_lot(db_path, ticker, shares, cost, days_ago):
    conn = sqlite3.connect(str(db_path))
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    conn.execute(
        "INSERT INTO cost_lots (ticker, shares, cost_per_share, purchase_date) VALUES (?,?,?,?)",
        (ticker, shares, cost, d),
    )
    conn.commit()
    conn.close()


# ── 0151: assignment floor compares strike, not current_price ─────────────────

def test_assignment_floor_uses_strike_not_current_price():
    """0151: strike below floor must reject even when current_price > floor."""
    ok, reason = _check_assignment_eligible(_ctx(
        current_price=205.0, strike=180.0, dte=5,
        delta=0.92, remaining_extrinsic=0.10,
        assignment_price_floor=190.0,
    ))
    assert not ok, "strike 180 < floor 190 should reject"
    assert "strike" in reason.lower()


def test_assignment_floor_passes_when_strike_above_floor():
    """0151: strike above floor should not block on gate 3."""
    ok, reason = _check_assignment_eligible(_ctx(
        current_price=205.0, strike=195.0, dte=5,
        delta=0.92, remaining_extrinsic=0.10,
        assignment_price_floor=190.0,
    ))
    assert ok, f"strike 195 > floor 190 should pass: {reason}"


def test_assignment_floor_not_set_passes():
    """No floor configured → gate 3 skipped."""
    ok, _ = _check_assignment_eligible(_ctx(
        current_price=180.0, strike=175.0, dte=3,
        delta=0.91, remaining_extrinsic=0.05,
        assignment_price_floor=None,
    ))
    assert ok


# ── 0157: tax friction uses strike (assignment_price), not current_price ──────

def test_lot_tax_friction_uses_strike_not_market_price(tmp_path, monkeypatch):
    """0157: gain must be shares × (strike − cost), not shares × (market − cost).

    330-day-old lot (35 days to LT crossover ≤ 90-day guard), basis=$100, 100 shares.
    At strike=$180: ST gain=$8,000, avoidable=$1,360 > $500 → triggers; reason shows $8,000.
    At market=$205: gain would be $10,500 (wrong) — reason would show $10,500 not $8,000.
    """
    db_path = _make_db(tmp_path)
    _insert_lot(db_path, "ANET", shares=100, cost=100.0, days_ago=330)
    _patch_db(monkeypatch, db_path)

    detail = _lot_tax_friction("ANET", assignment_price=180.0, shares_to_assign=100)

    assert detail.total_friction > 0, f"Expected friction>0 for large ST gain, got {detail.total_friction}"
    assert "8,000" in detail.reason, (
        f"Reason should show $8,000 ST gain (strike-based, not market-based), got: {detail.reason}"
    )
    assert detail.available is True


def test_lot_tax_friction_strike_near_basis_no_friction(tmp_path, monkeypatch):
    """0157: strike near basis → gain below threshold → no friction.

    If code used market ($210) instead of strike ($155):
    market gain = $6,000, avoidable = $1,020 → would incorrectly trigger.
    Strike gain = $500, avoidable = $85 → correct result is no trigger.
    """
    db_path = _make_db(tmp_path)
    _insert_lot(db_path, "ANET", shares=100, cost=150.0, days_ago=330)
    _patch_db(monkeypatch, db_path)

    detail = _lot_tax_friction("ANET", assignment_price=155.0, shares_to_assign=100)

    assert detail.total_friction == 0.0, (
        "Gain $500 → avoidable $85 should be below $500 threshold; "
        "if code wrongly used market price it would trigger"
    )


def test_lot_tax_friction_no_lots_unavailable(tmp_path, monkeypatch):
    """0171: empty lot list → available=False (data error, not zero friction)."""
    db_path = _make_db(tmp_path)
    _patch_db(monkeypatch, db_path)
    detail = _lot_tax_friction("NONE", assignment_price=200.0, shares_to_assign=100)
    assert detail.total_friction == 0.0
    assert detail.available is False, "Empty lots must set available=False (data error)"


def test_lot_tax_friction_lt_crossover_too_far_no_friction(tmp_path, monkeypatch):
    """LT crossover > 90 days away → guard returns 0 (deferral not justified)."""
    db_path = _make_db(tmp_path)
    _insert_lot(db_path, "TEST", shares=100, cost=100.0, days_ago=180)  # 185 days to LT crossover
    _patch_db(monkeypatch, db_path)
    detail = _lot_tax_friction("TEST", assignment_price=300.0, shares_to_assign=100)
    assert detail.total_friction == 0.0, "LT crossover 185 days away should suppress friction"


# ── 0158: FIFO lot selection stops at shares_to_assign ────────────────────────

def test_lot_tax_friction_fifo_stops_at_shares_to_assign(tmp_path, monkeypatch):
    """0158: 1 contract (100 shares) draws from LT lot first and never reaches the ST lot.

    Lots FIFO oldest-first: [200 LT @ 400d] → [100 ST @ 330d]
    100 shares requested → takes 100 from the 200-share LT lot; ST lot never touched → no friction.
    """
    db_path = _make_db(tmp_path)
    _insert_lot(db_path, "TEST", shares=200, cost=100.0, days_ago=400)  # LT, FIFO first
    _insert_lot(db_path, "TEST", shares=100, cost=100.0, days_ago=330)  # ST, not reached
    _patch_db(monkeypatch, db_path)

    detail = _lot_tax_friction("TEST", assignment_price=150.0, shares_to_assign=100)
    assert detail.total_friction == 0.0, "FIFO delivers 100 LT shares; ST lot unreached → no friction"


def test_lot_tax_friction_fifo_two_contracts_reaches_st_lot(tmp_path, monkeypatch):
    """0158: 2 contracts (200 shares) exhaust 100-share LT lot then draw 100 from ST lot.

    Lots FIFO oldest-first: [100 LT @ 400d] → [200 ST @ 330d]
    200 shares → 100 LT + 100 ST; 100 ST × ($170-$100) = $7,000 gain → avoidable $1,190.
    """
    db_path = _make_db(tmp_path)
    _insert_lot(db_path, "TEST", shares=100, cost=100.0, days_ago=400)  # LT
    _insert_lot(db_path, "TEST", shares=200, cost=100.0, days_ago=330)  # ST, 35 days to crossover
    _patch_db(monkeypatch, db_path)

    detail = _lot_tax_friction("TEST", assignment_price=170.0, shares_to_assign=200)
    assert detail.total_friction > 0, (
        f"2 contracts exhaust LT then draw 100 ST; gain $7,000 → avoidable $1,190 > threshold. "
        f"Got {detail.total_friction}"
    )


# ── 0161: conservative fail-safe when preserve_high_conviction and thesis unavailable ─

def test_preserve_high_conviction_no_thesis_blocks_assignment():
    """0161: preserve_high_conviction=True + no thesis → block (fail-safe)."""
    ok, reason = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_policy={"preserve_high_conviction": True, "min_conviction_to_preserve": 4},
        conviction=None,
        thesis_health=None,
    ))
    assert not ok, "Missing thesis should block when preserve_high_conviction=True"
    assert "unavailable" in reason.lower()


def test_preserve_high_conviction_no_scored_pillars_blocks_assignment():
    """0161: conviction present but thesis_health=None (no scored pillars) → block."""
    ok, reason = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_policy={"preserve_high_conviction": True, "min_conviction_to_preserve": 4},
        conviction=5,
        thesis_health=None,
    ))
    assert not ok, "Missing pillar scores should block when preserve_high_conviction=True"
    assert "unavailable" in reason.lower()


def test_preserve_high_conviction_false_allows_no_thesis():
    """0161: preserve_high_conviction=False → missing thesis doesn't block."""
    ok, _ = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_policy={"preserve_high_conviction": False},
        conviction=None,
        thesis_health=None,
    ))
    assert ok


def test_preserve_high_conviction_low_health_allows_assignment():
    """0161: thesis health below preservation threshold → assignment allowed."""
    ok, reason = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_policy={
            "preserve_high_conviction": True,
            "min_conviction_to_preserve": 4,
            "min_thesis_health_for_preservation": 80,
        },
        conviction=5,
        thesis_health=60.0,  # below 80 → not preserved
    ))
    assert ok, f"Health=60 below threshold=80 → allow assignment: {reason}"


def test_preserve_high_conviction_high_health_blocks_assignment():
    """0161: conviction ≥ min + health ≥ threshold → block assignment."""
    ok, reason = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_policy={
            "preserve_high_conviction": True,
            "min_conviction_to_preserve": 4,
            "min_thesis_health_for_preservation": 80,
        },
        conviction=5,
        thesis_health=88.0,
    ))
    assert not ok, "High-conviction healthy thesis should block"
    assert "high-conviction" in reason.lower()


# ── 0160: live snapshot weight for overweight gate ────────────────────────────

def test_overweight_gate_not_overweight_blocks():
    """0160: only_if_overweight=True + weight ≤ max → block assignment."""
    ok, reason = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_policy={"only_if_overweight": True},
        current_weight_pct=8.0,
        max_position_pct=10.0,
    ))
    assert not ok, "8% ≤ 10% max → not overweight → block"
    assert "overweight" in reason.lower()


def test_overweight_gate_overweight_allows():
    """0160: weight > max → overweight → assignment allowed on this gate."""
    ok, _ = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_policy={"only_if_overweight": True},
        current_weight_pct=13.5,
        max_position_pct=10.0,
    ))
    assert ok, "13.5% > 10% max → overweight → allow"


def test_overweight_gate_no_snapshot_fails_closed():
    """0170: only_if_overweight=True + current_weight_pct=None → fail closed (data unavailable)."""
    ok, reason = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_policy={"only_if_overweight": True},
        current_weight_pct=None,
        max_position_pct=10.0,
    ))
    assert not ok, "Missing weight data must block assignment — unknown risk should fail closed"
    assert "unavailable" in reason.lower()


# ── 0152: evaluate_cc_management_state unified hierarchy ─────────────────────

def test_cap_80_returns_btc():
    """Step 1: cap >= 80% always BUY_TO_CLOSE."""
    action, _ = evaluate_cc_management_state(_ctx(pct_captured=85.0, delta=0.20))
    assert action == "BUY_TO_CLOSE", f"cap=85% → BUY_TO_CLOSE, got {action}"


def test_high_delta_low_extrinsic_returns_allow_assignment():
    """Step 2: delta>=0.80, extrinsic<1%, no gates → ALLOW_ASSIGNMENT."""
    action, reason = evaluate_cc_management_state(_ctx(
        current_price=190.0, strike=180.0, dte=5,
        delta=0.88, pct_captured=70.0,
        remaining_extrinsic=0.50,  # 0.26% < 1%
    ))
    assert action == "ALLOW_ASSIGNMENT", f"Got {action}: {reason}"


def test_has_avoid_returns_roll_out():
    """Step 3: risk event → ROLL_OUT."""
    action, _ = evaluate_cc_management_state(_ctx(
        current_price=155.0, strike=165.0, dte=20,
        delta=0.35, pct_captured=50.0,
        has_avoid=True, remaining_extrinsic=2.0,
        risk_events=[{"severity": "avoid", "label": "earnings"}],
    ))
    assert action == "ROLL_OUT", f"has_avoid → ROLL_OUT, got {action}"


def test_itm_returns_roll_up_and_out():
    """Step 6: stock above strike → ROLL_UP_AND_OUT."""
    action, _ = evaluate_cc_management_state(_ctx(
        current_price=182.0, strike=180.0, dte=15,
        delta=0.65, pct_captured=60.0, remaining_extrinsic=2.5,
    ))
    assert action == "ROLL_UP_AND_OUT", f"ITM → ROLL_UP_AND_OUT, got {action}"


def test_otm_hold():
    """Step 7: well OTM, low delta → HOLD_CALL."""
    action, _ = evaluate_cc_management_state(_ctx(
        current_price=155.0, strike=170.0, dte=30,
        delta=0.22, pct_captured=40.0, remaining_extrinsic=3.0,
    ))
    assert action == "HOLD_CALL", f"OTM low delta → HOLD_CALL, got {action}"


def test_elevated_delta_returns_roll_up():
    """Step 7: delta>=0.30, not ITM → ROLL_UP."""
    action, _ = evaluate_cc_management_state(_ctx(
        current_price=162.0, strike=170.0, dte=30,
        delta=0.35, pct_captured=45.0, remaining_extrinsic=2.0,
    ))
    assert action == "ROLL_UP", f"delta=0.35 OTM → ROLL_UP, got {action}"


def test_expiring_worthless_returns_hold():
    """Step 4: DTE<=7, OTM → HOLD_CALL."""
    action, _ = evaluate_cc_management_state(_ctx(
        current_price=158.0, strike=170.0, dte=4,
        delta=0.15, pct_captured=70.0, remaining_extrinsic=0.20,
    ))
    assert action == "HOLD_CALL", f"DTE=4 OTM → HOLD_CALL, got {action}"


def test_allowed_false_blocks_assignment():
    """Gate 5: assignment_policy.allowed=False → no ALLOW_ASSIGNMENT."""
    action, _ = evaluate_cc_management_state(_ctx(
        current_price=190.0, strike=180.0, dte=5,
        delta=0.92, pct_captured=70.0, remaining_extrinsic=0.10,
        assignment_policy={"allowed": False},
    ))
    assert action != "ALLOW_ASSIGNMENT", f"allowed=False should block, got {action}"


def test_tax_friction_in_context_blocks_assignment():
    """Gate 4: pre-computed tax friction in context blocks assignment."""
    ok, reason = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_tax_friction=750.0,
        tax_friction_reason="ST tax friction: $750 avoidable tax",
    ))
    assert not ok, "Pre-computed tax friction should block"
    assert "750" in reason


# ── 0168: disposal_date = expiry, not today ────────────────────────────────────

def test_lot_lt_before_expiry_no_friction(tmp_path, monkeypatch):
    """0168: lot crossing LT threshold before call expiry → classified LT at disposal → no friction.

    Today: Sep 12. Lot goes LT in 13 days (Sep 25). Expiry: Oct 16 (34 days out).
    At disposal (Oct 16) the lot is already LT → no avoidable friction.
    """
    db_path = _make_db(tmp_path)
    # 352 days old → LT on day 366 = 14 days from today; expiry is 34 days out → LT at disposal
    _insert_lot(db_path, "EXP", shares=100, cost=100.0, days_ago=352)
    _patch_db(monkeypatch, db_path)

    expiry = (date.today() + timedelta(days=34)).isoformat()
    detail = _lot_tax_friction("EXP", assignment_price=300.0, shares_to_assign=100,
                               disposal_date=date.fromisoformat(expiry))
    assert detail.total_friction == 0.0, (
        f"Lot LT at expiry date → no friction, got {detail.total_friction}"
    )


def test_lot_lt_after_expiry_has_friction(tmp_path, monkeypatch):
    """0168: lot not yet LT at call expiry → still ST at disposal → friction reported.

    Lot goes LT in 50 days; expiry is only 20 days out → lot is still ST at disposal.
    """
    db_path = _make_db(tmp_path)
    # 315 days old → LT in 51 days; expiry 20 days out → still ST at expiry
    _insert_lot(db_path, "EXP2", shares=100, cost=100.0, days_ago=315)
    _patch_db(monkeypatch, db_path)

    expiry = (date.today() + timedelta(days=20)).isoformat()
    detail = _lot_tax_friction("EXP2", assignment_price=300.0, shares_to_assign=100,
                               disposal_date=date.fromisoformat(expiry))
    assert detail.total_friction > 0, (
        f"Lot still ST at expiry → friction expected, got {detail.total_friction}"
    )


# ── 0169: per-lot schedule ─────────────────────────────────────────────────────

def test_lot_schedule_populated(tmp_path, monkeypatch):
    """0169: TaxFrictionDetail.lot_schedule has one entry per FIFO lot consumed."""
    db_path = _make_db(tmp_path)
    _insert_lot(db_path, "SCHED", shares=100, cost=100.0, days_ago=400)  # LT
    _insert_lot(db_path, "SCHED", shares=100, cost=100.0, days_ago=330)  # ST
    _patch_db(monkeypatch, db_path)

    detail = _lot_tax_friction("SCHED", assignment_price=200.0, shares_to_assign=200)
    assert len(detail.lot_schedule) == 2, f"Expected 2 lot entries, got {len(detail.lot_schedule)}"
    lt_entry = detail.lot_schedule[0]
    st_entry = detail.lot_schedule[1]
    assert lt_entry["friction_contribution"] == 0.0, "LT lot contributes no friction"
    assert st_entry["friction_contribution"] > 0.0, "ST lot contributes friction"
    assert "lt_date" in lt_entry
    assert "allocated_shares" in lt_entry


# ── 0171: tax data failure gate ────────────────────────────────────────────────

def test_gate4_tax_data_unavailable_blocks_assignment(tmp_path, monkeypatch):
    """0171: tax_friction_available=False → Gate 4 blocks assignment."""
    ok, reason = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_tax_friction=0.0,
        tax_friction_reason="",
        tax_friction_available=False,
    ))
    assert not ok, "tax_data_unavailable must block assignment"
    assert "unavailable" in reason.lower()


def test_gate4_lt_lots_zero_friction_allows_assignment(tmp_path, monkeypatch):
    """0171: all LT lots → friction=0.0, available=True → Gate 4 passes."""
    db_path = _make_db(tmp_path)
    _insert_lot(db_path, "LT_ONLY", shares=100, cost=100.0, days_ago=400)
    _patch_db(monkeypatch, db_path)

    detail = _lot_tax_friction("LT_ONLY", assignment_price=200.0, shares_to_assign=100)
    assert detail.total_friction == 0.0
    assert detail.available is True

    ok, reason = _check_assignment_eligible(_ctx(
        delta=0.92, remaining_extrinsic=0.10,
        assignment_tax_friction=detail.total_friction,
        tax_friction_reason=detail.reason,
        tax_friction_available=detail.available,
    ))
    assert ok, f"LT lots → no friction → Gate 4 should pass: {reason}"


# ── 0173: roll chain resolution ───────────────────────────────────────────────

def test_roll_chain_terminates_at_allow_assignment():
    """0173: chain [ROLL, ALLOW_ASSIGNMENT] with two-hop candidates."""
    # First ctx → ROLL_UP (elevated delta, OTM)
    ctx0 = _ctx(current_price=162.0, strike=170.0, dte=30,
                delta=0.35, pct_captured=45.0, remaining_extrinsic=2.0)
    # Second ctx (roll target) → ALLOW_ASSIGNMENT (deep ITM, near-zero extrinsic)
    ctx1 = _ctx(current_price=190.0, strike=180.0, dte=5,
                delta=0.88, pct_captured=70.0, remaining_extrinsic=0.30)

    chain = evaluate_cc_roll_chain(ctx0, candidate_contexts=[ctx1], max_hops=2)
    assert len(chain) >= 2, f"Expected at least 2 hops, got {len(chain)}"
    assert chain[0][0] == "ROLL_UP", f"First hop should be ROLL_UP, got {chain[0][0]}"
    assert chain[-1][0] == "ALLOW_ASSIGNMENT", f"Last hop should be ALLOW_ASSIGNMENT, got {chain[-1][0]}"


def test_roll_chain_respects_max_hops():
    """0173: chain stops at max_hops even if all hops are ROLL."""
    roll_ctx = _ctx(current_price=162.0, strike=170.0, dte=30,
                    delta=0.35, pct_captured=45.0, remaining_extrinsic=2.0)
    candidates = [roll_ctx, roll_ctx]  # both are ROLL

    chain = evaluate_cc_roll_chain(roll_ctx, candidate_contexts=candidates, max_hops=1)
    assert len(chain) <= 2, f"max_hops=1 should limit chain to 2 entries (initial + 1 hop)"
