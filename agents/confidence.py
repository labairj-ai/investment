"""Deterministic confidence scoring for agent findings and recommendations.

Formula:  Confidence = 0.30*D + 0.20*F + 0.20*S + 0.15*A + 0.15*R

  D — Data completeness   (0–100, specific point breakdown)
  F — Freshness           (0–100, exponential half-life decay per source)
  S — Source quality      (0–100, tiered by authority)
  A — Agreement           (0–100, fraction of signals matching recommendation)
  R — Rule support        (0–100, deterministic-rule coverage fraction)

Confidence caps (applied after formula, in order):
  1. Live option quote + good liquidity  → max 95
  2. Ask proxy used                      → max 70
  3. Theoretical option pricing          → max 45
  4. Single news source                  → max 60
  5. Missing recent fundamentals         → max 65
  6. Critic verdict = CHALLENGE          → max 60
  7. Missing cost basis (tax rec only)   → max 40

No LLM calls anywhere in this module.
"""

import math
from .contracts import EvidenceBundle


# ---------------------------------------------------------------------------
# Source quality tiers
# ---------------------------------------------------------------------------

_SOURCE_QUALITY: dict[str, int] = {
    "official_filing":       100,
    "primary_release":        85,
    "reputable_news":         65,
    "secondary_commentary":   40,
}


# ---------------------------------------------------------------------------
# Component helpers
# ---------------------------------------------------------------------------

def _freshness(age: float, half_life: float) -> float:
    """Exponential decay returning value in [0, 1]."""
    return math.exp(-math.log(2) * age / half_life)


def _component_D(b: EvidenceBundle) -> float:
    score = 0.0
    if b.has_price:
        score += 15
    if b.financial_quarters >= 4:
        score += 20
    if b.has_macro_scores:
        score += 15
    if b.news_age_hours is not None and b.news_age_hours <= 6:
        score += 15
    if b.has_event_calendar:
        score += 10
    if b.has_cost_basis:
        score += 10
    if b.has_strategy_metadata:
        score += 15
    return score  # 0–100


def _component_F(b: EvidenceBundle) -> float:
    samples: list[float] = []
    if b.option_quote_age_min is not None:
        samples.append(_freshness(b.option_quote_age_min, half_life=5))
    if b.market_quote_age_min is not None:
        samples.append(_freshness(b.market_quote_age_min, half_life=15))
    if b.news_age_hours is not None:
        samples.append(_freshness(b.news_age_hours, half_life=6))
    if b.macro_market_age_hours is not None:
        samples.append(_freshness(b.macro_market_age_hours, half_life=1))
    if b.macro_class_age_days is not None:
        samples.append(_freshness(b.macro_class_age_days, half_life=7))
    if b.financial_stmt_next_filing_days is not None:
        days = b.financial_stmt_next_filing_days
        if days >= 0:
            samples.append(1.0)  # still current before next filing
        else:
            samples.append(_freshness(-days, half_life=30))  # overdue
    return (sum(samples) / len(samples)) * 100 if samples else 50.0


def _component_S(b: EvidenceBundle) -> float:
    return float(_SOURCE_QUALITY.get(b.source_quality, 40))


def _component_A(b: EvidenceBundle) -> float:
    if not b.signal_directions:
        return 50.0  # neutral — no signals to agree or disagree
    aligned = sum(1 for d in b.signal_directions if d == b.recommendation_direction)
    return aligned / len(b.signal_directions) * 100


def _component_R(b: EvidenceBundle) -> float:
    return max(0.0, min(1.0, b.rule_support)) * 100


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def calculate_confidence(evidence: EvidenceBundle) -> int:
    """Return a deterministic confidence score in [0, 100].

    All scoring is based on measurable properties of the evidence — no LLM calls.
    """
    d = _component_D(evidence)
    f = _component_F(evidence)
    s = _component_S(evidence)
    a = _component_A(evidence)
    r = _component_R(evidence)

    raw = 0.30 * d + 0.20 * f + 0.20 * s + 0.15 * a + 0.15 * r
    score = round(raw)

    # Cap 1 — live option quote with good liquidity
    if evidence.has_live_option_quote and evidence.option_liquidity_good:
        score = min(score, 95)
    # Cap 2 — ask proxy (no real-time bid/ask)
    if evidence.uses_ask_proxy:
        score = min(score, 70)
    # Cap 3 — theoretical option pricing (no market quote at all)
    if evidence.uses_theoretical_pricing:
        score = min(score, 45)
    # Cap 4 — single news source
    if evidence.news_source_count == 1:
        score = min(score, 60)
    # Cap 5 — missing recent fundamentals
    if not evidence.has_recent_fundamentals:
        score = min(score, 65)
    # Cap 6 — critic challenged the recommendation
    if evidence.critic_verdict == "CHALLENGE":
        score = min(score, 60)
    # Cap 7 — missing cost basis on a tax recommendation
    if evidence.is_tax_rec and not evidence.has_cost_basis:
        score = min(score, 40)

    return max(0, min(100, score))
