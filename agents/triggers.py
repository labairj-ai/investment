"""Deterministic trigger detection — no LLM calls.

detect_triggers() maps portfolio state to which agents should run and why.
Each TriggerEvent carries enough context that the receiving agent doesn't
need to re-derive why it was called.
"""
from dataclasses import dataclass, field

from .contracts import PortfolioSnapshot


@dataclass
class TriggerEvent:
    trigger_type: str          # layer_drift | cc_eligible | lot_timing | portfolio_scope | …
    agent_type: str            # which agent should handle this trigger
    trigger_key: str | None = None   # human-readable identifier (e.g. "L1", ticker)
    ticker: str | None = None         # None for portfolio-scope triggers
    context: dict = field(default_factory=dict)  # extra data for the agent


# Minimum shares to be CC-eligible (one standard contract = 100 shares)
_CC_MIN_SHARES = 100
# Layers where covered calls are appropriate
_CC_ELIGIBLE_LAYERS = {1, 2, 3}


def detect_triggers(snapshot: PortfolioSnapshot) -> list[TriggerEvent]:
    """Return all triggers active for the given snapshot. Pure function — no side effects."""
    from strategy_config import LAYER_TARGETS, DRIFT_THRESHOLD

    triggers: list[TriggerEvent] = []

    # ── Layer drift → Portfolio Guardian ──────────────────────────────────────
    for layer_num, weight_pct in snapshot.layer_weights.items():
        target = LAYER_TARGETS.get(layer_num, 0.0)
        drift = weight_pct - target
        if abs(drift) >= DRIFT_THRESHOLD:
            triggers.append(TriggerEvent(
                trigger_type="layer_drift",
                agent_type="portfolio_guardian",
                trigger_key=f"L{layer_num}",
                ticker=None,
                context={
                    "layer":    layer_num,
                    "target":   target,
                    "actual":   round(weight_pct, 2),
                    "drift_pp": round(drift, 2),
                },
            ))

    # ── CC eligibility → Covered Call Agent ───────────────────────────────────
    for h in snapshot.holdings:
        if h.layer in _CC_ELIGIBLE_LAYERS and h.shares >= _CC_MIN_SHARES:
            triggers.append(TriggerEvent(
                trigger_type="cc_eligible",
                agent_type="covered_call",
                trigger_key=h.ticker,
                ticker=h.ticker,
                context={
                    "shares": h.shares,
                    "layer":  h.layer,
                    "value":  round(h.market_value, 2),
                },
            ))

    # ── Portfolio-scope daily briefing (always fires) ─────────────────────────
    triggers.append(TriggerEvent(
        trigger_type="portfolio_scope",
        agent_type="briefing",
        trigger_key="daily",
        ticker=None,
        context={"total_value": snapshot.total_value},
    ))

    return triggers
