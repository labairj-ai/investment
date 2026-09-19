"""Shared strategy configuration constants — intentionally side-effect-free.

Single source of truth for composite score weights, minimum recommendation
threshold, and virtual book starting cash.  Import this module from:

  agents/opportunity_agent.py        — production scoring
  agents/learning/book_simulator.py  — virtual champion/challenger books
  scripts/freeze_baseline.py         — experiment baseline snapshot
  tests/                             — regression tests

Importing this module is pure: no DB access, no agent registration,
no heavy application imports.
"""
from __future__ import annotations

COMPOSITE_WEIGHTS: dict[str, float] = {
    "Q":  0.30,   # Quality (Buffett score)
    "V":  0.25,   # Value
    "PF": 0.20,   # Portfolio fit
    "C":  0.15,   # Catalyst
    "EC": 0.10,   # Economic context
}
"""Opportunity Hunter composite score weights by component name.
_composite() in opportunity_agent.py must derive its result from this dict.
"""

MIN_COMPOSITE: int = 45
"""Minimum composite score required to emit a RESEARCH recommendation."""

VIRTUAL_BOOK_STARTING_CASH: float = 100_000.0
"""Starting notional cash for champion/challenger virtual experiment books.

Intentionally larger than shadow_account_initial_capital ($10k) — the virtual
books use a larger notional for statistical sensitivity while the shadow
brokerage account operates under a smaller real-money risk limit.
"""
