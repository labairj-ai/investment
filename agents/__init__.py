from .contracts import (
    HoldingSnapshot,
    PortfolioSnapshot,
    AgentContext,
    AgentFinding,
    Recommendation,
    CriticReview,
)
from .orchestrator import run_agents, register_agent
from .triggers import TriggerEvent, detect_triggers
from .confidence import calculate_confidence
from . import thesis_agent          # registers thesis_monitor handler at import time
from . import covered_call_agent    # registers covered_call handler at import time
from . import portfolio_guardian    # registers portfolio_guardian handler at import time
from . import critic_agent          # registers critic handler at import time
from . import outcome_evaluator     # registers outcome_evaluator handler at import time
from . import opportunity_agent     # registers opportunity_hunter handler at import time
from . import tax_agent             # registers tax handler at import time
from . import sell_trim_agent       # registers sell_trim handler at import time
from . import briefing_agent        # registers briefing handler at import time

__all__ = [
    "HoldingSnapshot",
    "PortfolioSnapshot",
    "AgentContext",
    "AgentFinding",
    "Recommendation",
    "CriticReview",
    "run_agents",
    "register_agent",
    "TriggerEvent",
    "detect_triggers",
    "calculate_confidence",
    "sell_trim_agent",
    "briefing_agent",
]
