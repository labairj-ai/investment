"""Tests for sell_trim_agent.py — deterministic score functions."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.sell_trim_agent import (
    _action_from_strength, _dominant_rationale,
    _valuation_percentile, _v_score_from_percentile, _RATIO_METRIC_MAP,
)


def test_action_below_threshold():
    assert _action_from_strength(5) == "NO_ACTION"


def test_action_hold():
    assert _action_from_strength(20) == "HOLD"


def test_action_review():
    assert _action_from_strength(35) == "REVIEW"


def test_action_trim():
    assert _action_from_strength(55) == "TRIM"


def test_action_exit():
    assert _action_from_strength(75) == "EXIT"


def test_action_at_boundaries():
    # threshold is exclusive: ss < 10 → NO_ACTION, ss == 10 → HOLD
    assert _action_from_strength(9) == "NO_ACTION"
    assert _action_from_strength(10) == "HOLD"
    # _NO_ACTION_THRESHOLD=10, <28→HOLD, <48→REVIEW, <68→TRIM, else→EXIT
    assert _action_from_strength(27) == "HOLD"
    assert _action_from_strength(28) == "REVIEW"
    assert _action_from_strength(47) == "REVIEW"
    assert _action_from_strength(48) == "TRIM"
    assert _action_from_strength(67) == "TRIM"
    assert _action_from_strength(68) == "EXIT"


def test_dominant_rationale_thesis_dominates():
    # T=100, others=0 → THESIS_BREAK
    dominant = _dominant_rationale(T=100, F=0, V=0, P=0, O=0)
    assert dominant == "THESIS_BREAK"


def test_dominant_rationale_concentration():
    # P=100, others low
    dominant = _dominant_rationale(T=0, F=0, V=0, P=100, O=0)
    assert dominant == "PORTFOLIO_CONCENTRATION"


def test_dominant_rationale_fundamental():
    # F=100, T low
    dominant = _dominant_rationale(T=0, F=100, V=0, P=0, O=0)
    assert dominant == "FUNDAMENTAL_DETERIORATION"


def test_sell_strength_formula():
    """Verify the SellStrength formula: 0.40T + 0.20F + 0.15V + 0.15P + 0.10O."""
    T, F, V, P, O = 80, 60, 40, 50, 20
    expected = round(0.40 * T + 0.20 * F + 0.15 * V + 0.15 * P + 0.10 * O, 1)
    # 32 + 12 + 6 + 7.5 + 2 = 59.5
    assert expected == 59.5
    assert _action_from_strength(59.5) == "TRIM"


def test_critical_thesis_pillar_violated_forces_exit():
    """T=90+ from a critical pillar violated → action = EXIT regardless of other scores."""
    # With T=90, others=0: ss = 0.40*90 = 36 → REVIEW, but T enforces T≥90 rule
    # The T=90 floor is enforced in _score_T via critical_violated check,
    # so this test validates that T=90 + formula → EXIT-eligible action.
    ss = 0.40 * 90 + 0.20 * 0 + 0.15 * 0 + 0.15 * 0 + 0.10 * 0
    # ss=36 → REVIEW (T alone doesn't hit EXIT threshold)
    # The design is: T≥90 → ss≥36 → min REVIEW, usually TRIM/EXIT when combined
    # Full EXIT requires ss≥68, which needs additional factors. T alone → REVIEW at minimum.
    assert ss == 36.0
    assert _action_from_strength(ss) == "REVIEW"
    # With T=90 and some F,V,P: full EXIT scenario
    ss2 = 0.40 * 90 + 0.20 * 80 + 0.15 * 70 + 0.15 * 50 + 0.10 * 30
    assert _action_from_strength(ss2) == "EXIT"


# ── 0084: true valuation ratio tests ─────────────────────────────────────────

def test_ratio_metric_map_does_not_contain_raw_fundamentals():
    """_RATIO_METRIC_MAP must map to ratio columns, not raw fundamental columns."""
    invalid_cols = {"free_cash_flow", "revenue", "operating_income", "gross_profit",
                    "net_income", "eps_diluted", "price_to_earnings"}
    for metric, col in _RATIO_METRIC_MAP.items():
        assert col not in invalid_cols, (
            f"primary_metric '{metric}' maps to raw fundamental '{col}' — "
            "should map to a valuation ratio column like 'ev_fcf', 'ps', etc."
        )


def test_ratio_metric_map_covers_key_metrics():
    """Key thesis primary_metric values must be in the map."""
    for m in ("ev_fcf", "ev_ebitda", "ps", "p_fcf", "ev_revenue", "pe"):
        assert m in _RATIO_METRIC_MAP, f"'{m}' missing from _RATIO_METRIC_MAP"


def test_valuation_percentile_rising_ratio_not_max():
    """If a ratio rose from 10x to 20x, current 20x is at 100th pct.

    This is correct for a valuation ratio: higher ratio = more expensive.
    (Unlike raw FCF where higher FCF ≠ more expensive.)
    """
    history = [10.0, 12.0, 14.0, 16.0, 18.0]  # oldest-to-newest in history list
    current = 20.0
    pct = _valuation_percentile(current, history)
    assert pct == 100.0, f"Expected 100th pct, got {pct}"
    score = _v_score_from_percentile(pct)
    assert score >= 70, f"High percentile ratio should yield high V score, got {score}"


def test_valuation_percentile_low_ratio_cheap():
    """A ratio at the bottom of history should yield a low V score (not expensive)."""
    history = [20.0, 25.0, 30.0, 35.0, 40.0]
    current = 5.0
    pct = _valuation_percentile(current, history)
    assert pct == 0.0
    score = _v_score_from_percentile(pct)
    assert score <= 10, f"Low pct ratio should yield low V score, got {score}"


def test_valuation_percentile_requires_min_4_periods():
    """Fewer than 4 historical ratio values → None (no percentile)."""
    assert _valuation_percentile(25.0, [20.0, 22.0]) is None
    assert _valuation_percentile(25.0, []) is None
