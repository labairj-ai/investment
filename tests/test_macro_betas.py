"""Tests for beta math and concordance logic (0483, 0489)."""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from portfolio_ai import _is_concordance_warning, _beta_confidence


# ── Concordance direction tests ───────────────────────────────────────────────

def test_concordance_negative_beta_high_sensitivity():
    """rate_beta=-12 should not warn when rate_sensitivity=8 (both indicate high sensitivity)."""
    assert not _is_concordance_warning(rate_beta=-12.0, rate_sensitivity=8)


def test_concordance_positive_beta_low_sensitivity():
    """rate_beta=+1 should not warn when rate_sensitivity=2 (both indicate low sensitivity)."""
    assert not _is_concordance_warning(rate_beta=1.0, rate_sensitivity=2)


def test_concordance_reversed_warns_negative_beta_low_sensitivity():
    """rate_beta=-12 with rate_sensitivity=2 should warn (reversed)."""
    assert _is_concordance_warning(rate_beta=-12.0, rate_sensitivity=2)


def test_concordance_reversed_warns_positive_beta_high_sensitivity():
    """rate_beta=+1 with rate_sensitivity=8 should warn (reversed)."""
    assert _is_concordance_warning(rate_beta=1.0, rate_sensitivity=8)


def test_concordance_neutral_zone_no_warn():
    """rate_beta in neutral zone (-5 to -2) should never warn regardless of LLM score."""
    assert not _is_concordance_warning(rate_beta=-3.0, rate_sensitivity=5)
    assert not _is_concordance_warning(rate_beta=-3.0, rate_sensitivity=2)
    assert not _is_concordance_warning(rate_beta=-3.0, rate_sensitivity=8)


def test_concordance_boundary_below_threshold():
    """rate_beta=-5.1 (just below threshold) with low sensitivity=4 should warn."""
    assert _is_concordance_warning(rate_beta=-5.1, rate_sensitivity=4)


def test_concordance_boundary_above_threshold():
    """rate_beta=-1.9 (just above threshold) with high sensitivity=6 should warn."""
    assert _is_concordance_warning(rate_beta=-1.9, rate_sensitivity=6)


# ── Beta confidence tier tests ────────────────────────────────────────────────

def test_confidence_stronger():
    assert _beta_confidence(2.5) == "stronger"
    assert _beta_confidence(-2.1) == "stronger"


def test_confidence_suggestive():
    assert _beta_confidence(1.7) == "suggestive"
    assert _beta_confidence(-1.5) == "suggestive"


def test_confidence_weak():
    assert _beta_confidence(0.8) == "weak"
    assert _beta_confidence(-1.4) == "weak"


def test_confidence_none():
    assert _beta_confidence(None) == "insufficient_data"


# ── Synthetic regression truth (0489) ────────────────────────────────────────

def test_synthetic_regression_recovers_known_betas():
    """Multivariate OLS must recover injected true betas within tolerance."""
    np.random.seed(42)
    n = 104
    yield_chg = np.random.normal(0, 0.10, n)
    uup_ret   = np.random.normal(0, 0.5, n)
    spy_ret   = np.random.normal(0.1, 1.5, n)
    noise     = np.random.normal(0, 1.0, n)

    # True betas: rate=-5, usd=+2, market=0.8
    equity_pct = -5.0 * yield_chg + 2.0 * uup_ret + 0.8 * spy_ret + noise

    X = np.column_stack([np.ones(n), yield_chg, uup_ret, spy_ret])
    coeffs, _, _, _ = np.linalg.lstsq(X, equity_pct, rcond=None)
    rate_recovered   = coeffs[1]
    usd_recovered    = coeffs[2]
    market_recovered = coeffs[3]

    assert abs(rate_recovered - (-5.0)) < 1.5, f"rate_beta off: {rate_recovered:.2f}"
    assert abs(usd_recovered  - 2.0)    < 1.5, f"usd_beta off: {usd_recovered:.2f}"
    assert abs(market_recovered - 0.8)  < 0.5, f"market_beta off: {market_recovered:.2f}"


def test_spy_control_isolates_idiosyncratic_rate_beta():
    """Adding SPY control reduces omitted-variable bias in rate beta estimate."""
    np.random.seed(7)
    n = 104
    rate_factor = np.random.normal(0, 0.10, n)
    spy_ret     = np.random.normal(0.1, 1.5, n)
    noise       = np.random.normal(0, 0.5, n)

    # SPY correlates with yield changes; without control, rate beta is biased
    spy_contamination = 0.3 * rate_factor  # SPY partially driven by rates
    spy_actual = spy_ret + spy_contamination

    equity_pct = -5.0 * rate_factor + 0.8 * spy_actual + noise

    # Without SPY control: biased
    X_no_control = np.column_stack([np.ones(n), rate_factor])
    c_no, _, _, _ = np.linalg.lstsq(X_no_control, equity_pct, rcond=None)

    # With SPY control: less biased
    X_control = np.column_stack([np.ones(n), rate_factor, spy_actual])
    c_ctrl, _, _, _ = np.linalg.lstsq(X_control, equity_pct, rcond=None)

    bias_no_control = abs(c_no[1] - (-5.0))
    bias_control    = abs(c_ctrl[1] - (-5.0))
    assert bias_control < bias_no_control, (
        f"SPY control should reduce bias: without={bias_no_control:.2f}, with={bias_control:.2f}"
    )
