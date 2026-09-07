# Outcome Evaluator: Correct Modeling for TRIM, ALLOCATE, REBALANCE

- **ID:** 0063
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** P1
- **Depends:** 0061

## Problem

In `_compute_scenarios()`, the `else` branch covers HOLD / REVIEW / TRIM / ALLOCATE / REBALANCE and sets:

```python
agent_r = hold_r
```

This means: if the agent recommended "TRIM 40% of ANET," the evaluator computes `recommended_path_return` as if the user held 100% of ANET. That's not evaluating the recommendation — it's evaluating the exact opposite of what was recommended. Six months of outcomes data for TRIM and ALLOCATE recommendations will be meaningless.

## Proposed approach

### TRIM

Read `trim_fraction` from `action_payload`. If execution record exists (from 0061), use execution data. Otherwise:

```python
f = pl.get("trim_fraction", 0.5)  # default 50%
# Proceeds go to cash (risk-free return ≈ 0 over short horizons)
# or to replacement position if specified in payload
replacement = pl.get("replacement_ticker")
if replacement:
    repl_return = _ticker_price_at(replacement, horizon_date) / _ticker_price_at(replacement, entry_date) - 1
    agent_r = (1 - f) * hold_r + f * repl_return
else:
    agent_r = (1 - f) * hold_r  # trimmed portion earns 0 (cash)
```

### ALLOCATE

Evaluate the incremental capital return, not the existing position:

```python
# Use target ticker and capital amount from payload
alloc_ticker = pl.get("ticker") or ticker
alloc_return = _ticker_price_at(alloc_ticker, horizon_date) / _ticker_price_at(alloc_ticker, entry_date) - 1
agent_r = alloc_return
```

### REBALANCE

Model the before/after weights:

```python
from_ticker = pl.get("from_ticker")
to_ticker = pl.get("to_ticker")
fraction = pl.get("fraction", 0.5)
from_return = hold_r
to_return = _ticker_price_at(to_ticker, horizon_date) / _ticker_price_at(to_ticker, entry_date) - 1
agent_r = (1 - fraction) * from_return + fraction * to_return
```

### Fallback: mark as not_yet_evaluable

When no execution record exists (0061) and no payload contains the required fields, set:

```python
agent_r = None
actual_is_estimated = True
# Add notes: "TRIM outcome not evaluable without execution record"
```

This is better than silently computing hold_r and calling it the "recommended path."

### Payload contract

Add documentation (inline comments) for what TRIM/ALLOCATE/REBALANCE recommendations should put in `action_payload` for the evaluator to use. Enforce this in sell_trim_agent.py and opportunity_agent.py.

## Touches

- `agents/outcome_evaluator.py` — extend `_compute_scenarios()` with TRIM/ALLOCATE/REBALANCE branches
- `agents/sell_trim_agent.py` — ensure `trim_fraction` is in action_payload for TRIM
- `agents/opportunity_agent.py` — ensure `ticker` is in action_payload for ALLOCATE
- `agent_db.py` — no schema changes (uses existing fields)

## Done when

- [ ] TRIM: `recommended_path_return` = `(1-f)*hold_r` or blended with replacement ticker return
- [ ] ALLOCATE: `recommended_path_return` = return on the incremental allocation ticker
- [ ] REBALANCE: `recommended_path_return` = blended from/to return
- [ ] All three mark `actual_is_estimated = True` when execution record absent and payload incomplete
- [ ] sell_trim_agent includes `trim_fraction` in TRIM payloads
- [ ] Existing HOLD/REVIEW evaluations unchanged
- [ ] **Backend QA:** re-run outcome evaluator on historical TRIM recs; verify new values differ from hold_r
