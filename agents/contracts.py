"""Shared types that cross agent boundaries. No business logic here."""
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HoldingSnapshot:
    ticker: str
    layer: int
    shares: float
    avg_cost: float
    current_price: float
    market_value: float
    weight_pct: float


@dataclass
class PortfolioSnapshot:
    date: str                        # ISO date YYYY-MM-DD
    total_value: float
    holdings: list[HoldingSnapshot]
    layer_weights: dict[int, float]  # layer_num -> weight_pct
    macro_scores: dict[str, Any]     # ticker -> score dict
    generated_at: float              # unix timestamp


@dataclass
class AgentContext:
    run_id: int
    snapshot: PortfolioSnapshot
    trigger_type: str
    trigger_key: str | None = None
    ticker: str | None = None        # None for portfolio-scope agents


@dataclass
class AgentFinding:
    finding_type: str
    summary: str
    ticker: str | None = None
    severity: int = 50               # 0–100
    confidence: int = 50             # 0–100
    why_now: str | None = None
    metrics: dict | None = None
    evidence: dict | None = None
    expires_at: float | None = None


@dataclass
class Recommendation:
    ticker: str
    action: str                      # BUY, SELL, TRIM, HOLD, WRITE_CC, …
    recommendation_score: int = 50   # 0–100
    confidence: int = 50             # 0–100
    priority: str = "normal"         # low, normal, high, urgent
    why_now: str | None = None
    rationale: str | None = None
    counter_case: str | None = None
    no_action_case: str | None = None
    action_payload: dict | None = None
    valid_until: float | None = None


@dataclass
class CriticReview:
    recommendation_id: int
    verdict: str                     # APPROVE | APPROVE_WITH_CAUTION | CHALLENGE | VETO
    strongest_objection: str | None = None
    missing_evidence: list | None = None
    confidence_adjustment: int = 0   # –50 to +20
