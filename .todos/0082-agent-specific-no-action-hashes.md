# Make NO ACTION Input Hashes Agent-Specific

- **ID:** 0082
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** low
- **Depends:** none

## Problem

`compute_input_hash()` uses the same inputs for every agent: ticker, agent_type, price, thesis_version, latest_quarter. For agents like the CC agent, a recommendation can materially change because IV shifted, earnings moved inside the window, the open CC position changed, or the CC thesis policy was updated — while price and financial quarter remain identical. This means the CC agent would skip re-evaluation (due to matching hash) even when conditions changed substantially. Conversely, agents that only need price and thesis version accumulate unnecessary hash misses.

## Proposed approach

- Define per-agent hash input specs as a dict or dataclass in `orchestrator.py` or a new `agents/hash_spec.py`:
  ```python
  HASH_INPUTS = {
      "portfolio_guardian": ["price", "weight_pct", "layer"],
      "thesis_monitor":     ["thesis_version", "financial_period"],
      "covered_call":       ["price", "iv_snapshot", "earnings_date", "open_cc_id", "cc_policy_hash"],
      "tax":                ["price", "lot_count", "realized_ytd", "lt_eligible"],
      "opportunity_hunter": ["financial_period", "buffett_score", "portfolio_weight"],
      "sell_trim":          ["thesis_version", "financial_period", "valuation_percentile", "portfolio_weight"],
  }
  ```
- Pass the relevant context fields (drawn from snapshot, thesis, options data) into a new `compute_agent_hash(agent_type, ticker, context)` function.
- Fall back to the current generic hash if an agent type is not in the spec.
- Update `_run_single_agent()` in `orchestrator.py` and `_record_no_actions()` to use agent-specific hashes.

## Touches

- `agent_db.py` — `compute_input_hash()` or new `compute_agent_hash()`
- `agents/orchestrator.py` — hash input assembly in `_run_single_agent()` and `_record_no_actions()`
- `tests/test_agent_db.py` — update hash tests to reflect per-agent inputs

## Done when

- [ ] Each agent type uses a distinct set of inputs to compute its NO ACTION hash
- [ ] CC agent hash changes when IV snapshot or open CC changes, without requiring a price change
- [ ] Sell/trim agent hash changes when valuation_percentile changes
- [ ] All existing hash tests updated; new per-agent hash tests added
