"""Versioned advisor contracts. Request fields cannot carry authorization."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
import hashlib
import json
import math

ADVISOR_CONTRACT_VERSION = 'advisor-decision-v1'
ADVISOR_POLICY_VERSION = 'advisor-policy-v1'
PARSER_VERSION = 'advisor-parser-v1'
PROMPT_VERSION = 'advisor-explanation-v1'
SCORER_VERSION = 'canonical-comparison-6-v1'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


@dataclass(frozen=True)
class AdvisorTradeLegRequest:
    ticker: str
    semantics: str
    quantity: float
    side: str = 'TARGET'
    funding_leg: str | None = None


@dataclass(frozen=True)
class AdvisorDecisionRequest:
    raw_request: str
    intent: str
    legs: tuple[AdvisorTradeLegRequest, ...] = ()
    constraints: tuple[str, ...] = ()
    parser_version: str = PARSER_VERSION
    parser_prompt_version: str = 'advisor-extraction-v1'
    model: str | None = None
    needs_clarification: bool = False
    issues: tuple[str, ...] = ()

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class AdvisorProposal:
    request: dict
    impact: dict
    context_hash: str
    evidence_refs: dict = field(default_factory=dict)
    origin: str = 'advisor'

    def to_dict(self):
        return asdict(self)
