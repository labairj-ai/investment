# Outcome-Aware Preference Learning: Separate Decision Quality Model

- **ID:** 0069
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** P2
- **Depends:** 0061, 0063

## Problem

The current Preference Learner correctly captures behavioral patterns ("RJ tends to reject high-delta calls") without silently modifying hard investment rules. That's the right first step.

But the next evolution is not just *what* the user prefers — it's *when the user is right*. The risk is that without separating these models, the system optimizes for agreement rather than investing quality. It becomes better at predicting what you'll accept, not better at telling you what you should do.

Example of the problem: if the user has consistently rejected every TRIM recommendation for 18 months, and those TRIM recommendations would have outperformed by 4% on average, the preference learner should not silently stop issuing TRIM recommendations — it should surface the performance gap.

## Proposed approach

### Keep preference model separate and unchanged

The existing `preference_learner.py` learns behavioral patterns:
- Tends to reject high-delta calls
- Tends to accept TRIM above 30% gain
- Prefers longer expiration on CC

This model is valuable for UX (pre-filtering, surfacing most likely actionable recommendations). Do not modify it. Do not fold outcome data into it.

### Build a separate Decision Quality Model

A new module: `agents/decision_quality.py`

```python
"""Decision Quality Model — tracks when user override outperforms or underperforms agent.

Separate from PreferenceLearner. Only consulted after execution/outcome data is mature.
Never used to silence recommendations; only used to add calibrated confidence to
'the agent tends to be right on X vs. user override' signals.
"""
```

It computes per-(agent_type, action, rationale_class) outcome statistics:
```python
{
    "sell_trim / EXIT / THESIS_BREAK": {
        "n_accepted": 12, "n_rejected": 8,
        "accepted_vs_spy": +2.1%,   # alpha when user followed agent
        "rejected_vs_spy": +0.4%,   # alpha when user overrode (held)
        "agent_edge": +1.7%         # following agent was better by this much
    },
    "covered_call / SELL_CC / high_delta": {
        "n_accepted": 5, "n_rejected": 31,
        "agent_edge": -3.2%         # user was right to reject high-delta calls
    }
}
```

### Usage

The Decision Quality Model is **read-only from the recommendation pipeline**. It:
- Adds a `decision_quality_note` to the LLM prompt when patterns are statistically significant (n ≥ 10 outcomes)
- Example: "Historical note: user has overridden EXIT/THESIS_BREAK 8 times; agent recommendation outperformed by avg 1.7% over 6 months. Consider following this signal."
- Never changes thresholds, never suppresses recommendations
- Only activates when outcome data is trustworthy (requires 0061 execution ledger + 0063 modeling)

### Statistical safeguards

- Minimum n=10 outcomes before computing edge
- Minimum horizon: 3-month outcomes preferred (not 1-week)
- Confidence interval reporting: report "agent_edge = +1.7% ± 2.1%" — if CI crosses zero, note not statistically significant

## Touches

- `agents/decision_quality.py` (new module)
- `agent_db.py` — helper to query `recommendation_outcomes` grouped by agent_type + action + rationale_class
- `agents/sell_trim_agent.py` — optionally inject `decision_quality_note` into LLM prompt when available
- `agents/preference_learner.py` — no changes; explicitly document the separation

## Done when

- [ ] `decision_quality.py` exists as a separate module from `preference_learner.py`
- [ ] Per-(agent, action, rationale_class) outcome statistics computed from `recommendation_outcomes`
- [ ] Statistical significance gate: n ≥ 10 outcomes before surfacing any edge signal
- [ ] Decision quality note injected into sell_trim and covered_call agent prompts when significant
- [ ] Note never suppresses recommendation, only adds calibrated historical context
- [ ] Module-level docstring explicitly documents the separation from preference learning and why
- [ ] **Prerequisite check:** this todo should not be started until 0061 and 0063 have mature outcome data (≥ 3 months of execution records)
