from __future__ import annotations
"""Decision Quality Model — tracks when user override outperforms or underperforms agent.

DISTINCT from PreferenceLearner (agents/preference_learner.py), which learns
behavioral patterns. This module asks a different question:

    Preference Model:  "What does the user tend to prefer?"
    Decision Quality:  "When is the user right vs the agent?"

Do NOT combine. If we fold outcomes into preference learning, the system
optimises for agreement rather than investing quality — it becomes better at
predicting what you'll accept, not at telling you what you should do.

This module is READ-ONLY from the recommendation pipeline: it injects a
calibrated note into LLM prompts when patterns are statistically significant
(n ≥ 10 confirmed outcomes at ≥ 3-month horizons), but NEVER:
  - Changes recommendation thresholds
  - Suppresses recommendations
  - Modifies confidence scores

Activation prerequisite: requires the executed_actions ledger (0061) and
TRIM/ALLOCATE outcome modeling (0063) to produce trustworthy actual_return
values before any meaningful signal can emerge.
"""
import math
from typing import Optional

import agent_db

_MIN_SAMPLES = 10       # minimum matured outcomes before surfacing any note
_CI_THRESHOLD = 0.02    # minimum |agent_edge| to be actionable (2%)


def compute_quality_stats() -> list[dict]:
    """Compute per-(agent_type, action, rationale_class) outcome statistics.

    Returns a list of dicts with keys:
      agent_type, action, rationale_class,
      n, avg_actual, avg_agent, avg_hold, avg_spy,
      avg_user_override_alpha, n_accepted, n_rejected,
      agent_edge (avg_agent - avg_hold, agent rec vs just holding),
      agent_edge_variance, ci_lower, ci_upper (0080: 95% confidence interval)

    Only includes categories with n >= _MIN_SAMPLES non-estimated outcomes.
    """
    rows = agent_db.get_outcome_statistics_by_category(min_samples=_MIN_SAMPLES)
    result = []
    for r in rows:
        agent_edge = None
        if r.get("avg_agent") is not None and r.get("avg_hold") is not None:
            agent_edge = r["avg_agent"] - r["avg_hold"]

        # 0080: compute variance and 95% CI from stored variance column
        n = r.get("n") or 1
        variance = r.get("agent_edge_variance") or 0.0
        std = math.sqrt(max(float(variance), 0.0))
        ci_half = 1.96 * std / math.sqrt(n) if n > 1 else float("inf")
        ci_lower = agent_edge - ci_half if agent_edge is not None else None
        ci_upper = agent_edge + ci_half if agent_edge is not None else None

        result.append({
            **r,
            "agent_edge": agent_edge,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
        })
    return result


def _simple_ci_half_width(values_std: float, n: int) -> float:
    """Approximate 95% CI half-width using normal approximation."""
    if n <= 1:
        return float("inf")
    return 1.96 * values_std / math.sqrt(n)


def get_decision_quality_note(
    agent_type: str,
    action: str,
    rationale_class: Optional[str] = None,
) -> str:
    """Return a calibrated historical note for injection into an LLM prompt.

    Returns an empty string when:
    - Fewer than _MIN_SAMPLES outcomes exist for this category
    - The agent_edge is below _CI_THRESHOLD (not material)
    - Outcome data is not yet trustworthy (estimated outcomes dominate)
    - 0080: The 95% CI crosses zero (statistically indistinguishable from zero)

    The note is purely informational — the LLM prompt instructions should make
    clear it does not change the action or confidence.
    """
    stats = compute_quality_stats()

    # Match on (agent_type, action), then narrow by rationale_class if provided
    matches = [
        s for s in stats
        if s["agent_type"] == agent_type and s["action"] == action
    ]
    if rationale_class:
        specific = [s for s in matches if s.get("rationale_class") == rationale_class]
        if specific:
            matches = specific

    if not matches:
        return ""

    # Use the match with most samples
    best = max(matches, key=lambda s: s["n"])

    n          = best["n"]
    edge       = best.get("agent_edge")
    n_accepted = best.get("n_accepted") or 0
    n_rejected = best.get("n_rejected") or 0

    if edge is None or abs(edge) < _CI_THRESHOLD:
        return ""

    # 0080: require CI does not cross zero (must be statistically clear)
    ci_lower = best.get("ci_lower", float("-inf"))
    ci_upper = best.get("ci_upper", float("inf"))
    if ci_lower is not None and ci_upper is not None:
        if ci_lower < 0 < ci_upper:
            return ""  # CI crosses zero — statistically indistinguishable from zero

    direction = "outperformed" if edge > 0 else "underperformed"
    pct = abs(edge * 100)
    note = (
        f"Historical context (n={n} outcomes, ≥3m horizons): "
        f"following this agent recommendation {direction} holding by "
        f"{pct:.1f}% on average. "
        f"Accepted {n_accepted}x / Rejected {n_rejected}x historically. "
        f"This is informational only — it does not change the recommended action."
    )
    return note


def inject_into_prompt(
    base_prompt: str,
    agent_type: str,
    action: str,
    rationale_class: Optional[str] = None,
) -> str:
    """Append a decision quality note to a prompt string if a significant pattern exists."""
    note = get_decision_quality_note(agent_type, action, rationale_class)
    if note:
        return base_prompt + f"\n\nHISTORICAL DECISION QUALITY: {note}"
    return base_prompt
