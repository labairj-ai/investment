"""Regime stress direction and missing-data semantics tests (0487, 0488, 0489)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from portfolio_ai import compute_regime_stress, compute_regime_adjusted_risk, is_fund, SECURITY_MASTER


# ── Regime direction tests ────────────────────────────────────────────────────

def _regime_with_rate(yield_63d_bps):
    return {"rate": {"yield_10y_63d_chg_bps": yield_63d_bps}, "dollar": {}, "volatility": {}}


def _regime_with_dollar(uup_63d_pct):
    return {"rate": {}, "dollar": {"uup_63d_pct": uup_63d_pct}, "volatility": {}}


def test_rising_rates_positive_stress():
    """Rising rates (+100bps over 63d) → positive rate_stress (adverse for rate-sensitive names)."""
    s = compute_regime_stress(_regime_with_rate(100))
    assert s.get("rate_stress") is not None
    assert s["rate_stress"] > 0, f"Expected positive rate_stress for rising rates, got {s['rate_stress']}"


def test_falling_rates_nonpositive_stress():
    """Falling rates (-100bps over 63d) → non-positive rate_stress (favorable)."""
    s = compute_regime_stress(_regime_with_rate(-100))
    assert s.get("rate_stress") is not None
    assert s["rate_stress"] <= 0, f"Expected non-positive rate_stress for falling rates, got {s['rate_stress']}"


def test_falling_rates_negative_stress():
    """Falling rates → negative stress (favorable interaction)."""
    s = compute_regime_stress(_regime_with_rate(-100))
    assert s["rate_stress"] < 0, f"Expected negative rate_stress for -100bps, got {s['rate_stress']}"


def test_missing_rate_data_is_none():
    """Missing rate data → rate_stress is None, not 0 (missing ≠ benign)."""
    s = compute_regime_stress({"rate": {}, "dollar": {}, "volatility": {}})
    assert s.get("rate_stress") is None, f"Expected None for missing rate data, got {s.get('rate_stress')}"


def test_strong_dollar_positive_stress():
    """Strengthening dollar (+3% over 63d) → positive dollar_stress."""
    s = compute_regime_stress(_regime_with_dollar(3.0))
    assert s.get("dollar_stress") is not None
    assert s["dollar_stress"] > 0, f"Expected positive dollar_stress, got {s['dollar_stress']}"


def test_weakening_dollar_nonpositive_stress():
    """Weakening dollar (-3%) → non-positive dollar_stress (favorable)."""
    s = compute_regime_stress(_regime_with_dollar(-3.0))
    assert s.get("dollar_stress") is not None
    assert s["dollar_stress"] <= 0, f"Expected non-positive dollar_stress, got {s['dollar_stress']}"


def test_missing_dollar_data_is_none():
    """Missing dollar data → dollar_stress is None."""
    s = compute_regime_stress({"rate": {}, "dollar": {}, "volatility": {}})
    assert s.get("dollar_stress") is None, f"Expected None for missing dollar data, got {s.get('dollar_stress')}"


def test_geopolitical_stress_is_none():
    """Geopolitical stress is always None — no real signal source yet."""
    s = compute_regime_stress({"rate": {"yield_10y_63d_chg_bps": 100}, "dollar": {}, "volatility": {}})
    assert s.get("geopolitical_stress") is None, f"Expected None geopolitical stress, got {s.get('geopolitical_stress')}"


def test_stress_range_clamp():
    """rate_stress is clamped to [-1, +1]."""
    s_high = compute_regime_stress(_regime_with_rate(1000))
    s_low  = compute_regime_stress(_regime_with_rate(-1000))
    assert s_high["rate_stress"] <= 1.0
    assert s_low["rate_stress"]  >= -1.0


# ── Regime-adjusted risk interaction semantics ────────────────────────────────

def test_signed_interaction_adverse_is_positive():
    """Rising rates (positive rate_stress) + high rate sensitivity → positive regime-adjusted risk."""
    scores = {"rate_sensitivity": {"score": 8}, "dollar_sensitivity": {"score": 3},
              "inflation_hedge": {"score": 5}, "geopolitical_risk": {"score": 3}}
    stress = {"rate_stress": 0.5, "dollar_stress": 0.0, "vol_stress": 0.2, "geopolitical_stress": None, "note": "x"}
    adj = compute_regime_adjusted_risk(scores, stress)
    assert adj is not None
    assert adj.get("rate_sensitivity_regime_risk") is not None
    assert adj["rate_sensitivity_regime_risk"] > 0


def test_signed_interaction_favorable_is_negative():
    """Falling rates (negative rate_stress) + high rate sensitivity → negative interaction."""
    scores = {"rate_sensitivity": {"score": 8}, "dollar_sensitivity": {"score": 3},
              "inflation_hedge": {"score": 5}, "geopolitical_risk": {"score": 3}}
    stress = {"rate_stress": -0.5, "dollar_stress": 0.0, "vol_stress": 0.2, "geopolitical_stress": None, "note": "x"}
    adj = compute_regime_adjusted_risk(scores, stress)
    assert adj is not None
    assert adj["rate_sensitivity_regime_risk"] < 0


def test_none_stress_propagates_to_none_interaction():
    """When rate_stress is None, rate interaction result is None."""
    scores = {"rate_sensitivity": {"score": 8}, "dollar_sensitivity": {"score": 5},
              "inflation_hedge": {"score": 5}, "geopolitical_risk": {"score": 3}}
    stress = {"rate_stress": None, "dollar_stress": 0.3, "vol_stress": 0.2, "geopolitical_stress": None, "note": "x"}
    adj = compute_regime_adjusted_risk(scores, stress)
    assert adj is not None
    assert adj.get("rate_sensitivity_regime_risk") is None


# ── Fund classification tests (0486, 0489) ────────────────────────────────────

def test_known_funds_classified_as_funds():
    for ticker in ["VTSAX", "VFIAX", "VTMGX", "FSPTX", "SPY", "QQQ", "SCHD", "BIL", "VNQ", "TLT"]:
        assert is_fund(ticker), f"{ticker} should be classified as a fund"


def test_mstr_is_not_a_fund():
    assert not is_fund("MSTR"), "MSTR is a company (MicroStrategy), not a fund"


def test_known_companies_are_not_funds():
    for ticker in ["AAPL", "GRMN", "NVDA", "AMZN", "GOOGL", "TSLA"]:
        assert not is_fund(ticker), f"{ticker} should be classified as a company"


def test_vtsax_in_security_master():
    assert "VTSAX" in SECURITY_MASTER
    assert SECURITY_MASTER["VTSAX"]["security_type"] == "mutual_fund"


def test_vtmgx_in_security_master():
    assert "VTMGX" in SECURITY_MASTER
    assert SECURITY_MASTER["VTMGX"]["security_type"] == "mutual_fund"


# ── Provenance round-trip (0484, 0489) ────────────────────────────────────────

def test_evidence_hash_deterministic():
    """SHA-256 of evidence dict must be deterministic across calls."""
    import hashlib, json
    evidence = {"sector": "Technology", "net_debt": 1e9, "foreign_rev_pct": 0.45,
                "gross_margin_pct": 0.65, "interest_coverage": 12.5, "revenue_ttm": 5e9}
    h1 = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
    assert h1 == h2
    assert len(h1) == 64  # full SHA-256, no truncation


def test_evidence_hash_changes_with_data():
    """Different evidence dicts must produce different hashes."""
    import hashlib, json
    ev1 = {"sector": "Technology", "net_debt": 1e9}
    ev2 = {"sector": "Healthcare", "net_debt": 1e9}
    h1 = hashlib.sha256(json.dumps(ev1, sort_keys=True).encode()).hexdigest()
    h2 = hashlib.sha256(json.dumps(ev2, sort_keys=True).encode()).hexdigest()
    assert h1 != h2


# ── Signed interaction quadrant tests (0491) ─────────────────────────────────
# Full pipeline: regime dict → compute_regime_stress → compute_regime_adjusted_risk

def _structural(rate=5, dollar=5, inflation_hedge=5, geo=5):
    return {
        "rate_sensitivity": {"score": rate},
        "dollar_sensitivity": {"score": dollar},
        "inflation_hedge": {"score": inflation_hedge},
        "geopolitical_risk": {"score": geo},
    }


def test_rising_rates_high_sensitivity_adverse():
    """Rising rates + high rate_sensitivity → positive (adverse) interaction."""
    regime = {"rate": {"yield_10y_63d_chg_bps": 120}, "dollar": {}, "volatility": {}}
    stress = compute_regime_stress(regime)
    interactions = compute_regime_adjusted_risk(_structural(rate=9), stress)
    assert interactions is not None
    val = interactions.get("rate_sensitivity_regime_risk")
    assert val is not None and val > 0, f"Expected positive adverse interaction, got {val}"


def test_falling_rates_high_sensitivity_favorable():
    """Falling rates + high rate_sensitivity → negative (favorable) interaction."""
    regime = {"rate": {"yield_10y_63d_chg_bps": -120}, "dollar": {}, "volatility": {}}
    stress = compute_regime_stress(regime)
    interactions = compute_regime_adjusted_risk(_structural(rate=9), stress)
    assert interactions is not None
    val = interactions.get("rate_sensitivity_regime_risk")
    assert val is not None and val < 0, f"Expected negative favorable interaction, got {val}"


def test_high_inflation_high_hedge_mitigating():
    """High inflation stress (proxied by rising rates) + high inflation_hedge → negative (mitigating)."""
    regime = {"rate": {"yield_10y_63d_chg_bps": 150}, "dollar": {}, "volatility": {}}
    stress = compute_regime_stress(regime)
    interactions = compute_regime_adjusted_risk(_structural(inflation_hedge=9), stress)
    assert interactions is not None
    val = interactions.get("inflation_hedge_regime_risk")
    assert val is not None and val < 0, f"Expected negative (mitigating) inflation_hedge interaction, got {val}"


def test_high_inflation_low_hedge_no_protection():
    """High inflation stress + low inflation_hedge → near-zero (score=1 → norm=0)."""
    regime = {"rate": {"yield_10y_63d_chg_bps": 150}, "dollar": {}, "volatility": {}}
    stress = compute_regime_stress(regime)
    interactions = compute_regime_adjusted_risk(_structural(inflation_hedge=1), stress)
    assert interactions is not None
    val = interactions.get("inflation_hedge_regime_risk")
    assert val is None or abs(val) < 0.05, f"Expected near-zero for low hedge, got {val}"


def test_unknown_regime_input_produces_none_interaction():
    """Missing regime data → None interaction (not zero)."""
    stress = compute_regime_stress({"rate": {}, "dollar": {}, "volatility": {}})
    interactions = compute_regime_adjusted_risk(_structural(rate=9, dollar=9), stress)
    assert interactions is not None
    assert interactions.get("rate_sensitivity_regime_risk") is None, \
        f"Missing rate data should produce None interaction, got {interactions.get('rate_sensitivity_regime_risk')}"
    assert interactions.get("dollar_sensitivity_regime_risk") is None, \
        f"Missing dollar data should produce None interaction, got {interactions.get('dollar_sensitivity_regime_risk')}"


def test_interaction_version_stored():
    """compute_regime_adjusted_risk result carries interaction_version."""
    from portfolio_ai import MACRO_INTERACTION_VERSION
    stress = {"rate_stress": 0.5, "dollar_stress": 0.2, "vol_stress": 0.3, "geopolitical_stress": None, "note": "x"}
    interactions = compute_regime_adjusted_risk(_structural(), stress)
    assert interactions is not None
    assert interactions.get("interaction_version") == MACRO_INTERACTION_VERSION
