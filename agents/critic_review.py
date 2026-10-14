"""Review evidence contract shared by governance adapters, not producer scoring."""
from __future__ import annotations
from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class CriticReviewInput:
    origin: str
    ticker: str
    action: str
    decision_kind: str
    trade_impact: dict
    thesis: dict | None
    context_hash: str
    layer_before: dict
    layer_after: dict
    recommendation_score: float | None = None
    confidence: float | None = None
    learning_eligible: bool = False
    review_contract_version: str = 'critic-review-v1'

    def to_dict(self):
        return asdict(self)
