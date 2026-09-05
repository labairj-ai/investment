"""Shared types that cross agent boundaries. No business logic here."""
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Evidence bundle — input to confidence scoring
# ---------------------------------------------------------------------------

@dataclass
class EvidenceBundle:
    # D — data completeness (each field maps to specific point value)
    has_price: bool = False
    financial_quarters: int = 0         # ≥4 earns full points
    has_macro_scores: bool = False
    news_age_hours: float | None = None  # None = no news available
    has_event_calendar: bool = False
    has_cost_basis: bool = False
    has_strategy_metadata: bool = False  # thesis + layer assignment present

    # F — freshness ages (None = source not used; units per field name)
    option_quote_age_min: float | None = None
    market_quote_age_min: float | None = None
    macro_market_age_hours: float | None = None
    macro_class_age_days: float | None = None
    # positive = days until next filing (still current); negative = days overdue
    financial_stmt_next_filing_days: float | None = None

    # S — best source quality used
    source_quality: str = "secondary_commentary"  # see _SOURCE_QUALITY map

    # A — directional agreement
    signal_directions: list[str] = field(default_factory=list)
    recommendation_direction: str = "neutral"

    # R — deterministic rule coverage
    rule_support: float = 0.0  # 0.0–1.0

    # Caps
    has_live_option_quote: bool = False
    option_liquidity_good: bool = False
    uses_ask_proxy: bool = False
    uses_theoretical_pricing: bool = False
    news_source_count: int = 0
    has_recent_fundamentals: bool = True
    critic_verdict: str | None = None   # "APPROVE" | "CHALLENGE" | "VETO" | …
    is_tax_rec: bool = False             # gates the cost-basis cap


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
