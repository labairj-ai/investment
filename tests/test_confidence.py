"""Tests for confidence.py — deterministic scoring and caps."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.confidence import calculate_confidence
from agents.contracts import EvidenceBundle


def _full_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        has_price=True,
        financial_quarters=4,
        has_macro_scores=True,
        news_age_hours=2.0,
        has_event_calendar=True,
        has_cost_basis=True,
        has_strategy_metadata=True,
        market_quote_age_min=5.0,
        source_quality="primary_release",
        signal_directions=["sell", "sell", "sell"],
        recommendation_direction="sell",
        rule_support=0.9,
    )


def test_full_bundle_high_score():
    score = calculate_confidence(_full_bundle())
    assert score >= 70, f"Expected ≥70, got {score}"
    assert 0 <= score <= 100


def test_theoretical_pricing_cap():
    b = _full_bundle()
    b.uses_theoretical_pricing = True
    score = calculate_confidence(b)
    assert score <= 45, f"Theoretical pricing should cap at 45, got {score}"


def test_critic_challenge_cap():
    b = _full_bundle()
    b.critic_verdict = "CHALLENGE"
    score = calculate_confidence(b)
    assert score <= 60, f"CHALLENGE cap should limit to 60, got {score}"


def test_missing_fundamentals_cap():
    b = _full_bundle()
    b.has_recent_fundamentals = False
    score = calculate_confidence(b)
    assert score <= 65, f"Missing fundamentals cap should limit to 65, got {score}"


def test_no_evidence_returns_reasonable():
    b = EvidenceBundle()
    score = calculate_confidence(b)
    assert 0 <= score <= 100


def test_ask_proxy_cap():
    b = _full_bundle()
    b.uses_ask_proxy = True
    score = calculate_confidence(b)
    assert score <= 70


def test_tax_rec_no_cost_basis_cap():
    b = _full_bundle()
    b.is_tax_rec = True
    b.has_cost_basis = False
    score = calculate_confidence(b)
    assert score <= 40
