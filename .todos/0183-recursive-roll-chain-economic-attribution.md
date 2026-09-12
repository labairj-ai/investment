# Recursive Roll Chain: Accumulate Full Option Cash Flows

- **ID:** 0183
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** high
- **Depends:** none

## Problem

`_resolve_chain()` in `outcome_evaluator.py` correctly walks `parent_cc_rec_id` to find the terminal action and chain depth, but it does not accumulate the net option cash flows of intermediate hops. The root roll's `actual_r` is calculated using only the root's `net_credit` (its own STO − BTC), ignoring all subsequent rolls' credits/debits and the terminal action's cash flow.

Concrete example (reviewer):
- Roll 1: BTC $4, STO $5 → +$1/share net (root, currently used)
- Roll 2: BTC $7, STO $9 → +$2/share net (intermediate, currently ignored)
- Final BTC: −$1/share (terminal, currently ignored)
- Full option P&L: +$1 + $2 − $1 = +$2/share

Current code produces `actual_r` using only the +$1, systematically understating multi-hop returns.

The terminal stock payoff (base_r) is correctly revised based on the terminal action, but the option side is incomplete.

## Proposed approach

1. Change `_resolve_chain()` return signature:
   ```python
   def _resolve_chain(start_rec_id, depth=0, max_depth=10, accumulated_credit=0.0):
       # returns (terminal_child, chain_open, chain_depth, cumulative_extra_credit)
   ```
   `cumulative_extra_credit` is the sum of all *subsequent* roll credits — the root's own net_credit is added at the call site, not inside.

2. At each intermediate ROLL child, fetch its execution record:
   ```python
   child_exec = agent_db.aggregate_executions(
       agent_db.get_executions_for_rec(child["id"]), child_action
   )
   if child_exec and child_exec.get("execution_price"):
       child_btc = float(child_exec["execution_price"])
       child_sto = float(child_exec.get("sto_premium") or 0.0)
       hop_credit = child_sto - child_btc
   else:
       hop_credit = 0.0   # no exec record → can't attribute, leave estimated
   return _resolve_chain(child["id"], depth + 1, max_depth, accumulated_credit + hop_credit)
   ```

3. At a terminal BTC child, also include that final BTC cash flow (negative cost to close):
   ```python
   if child_action == "BUY_TO_CLOSE":
       terminal_exec = agent_db.aggregate_executions(...)
       terminal_btc = float(terminal_exec["execution_price"]) if terminal_exec else None
       extra_credit = accumulated_credit - terminal_btc if terminal_btc else accumulated_credit
       return child, False, depth + 1, extra_credit
   ```

4. At a terminal ALLOW_ASSIGNMENT child, accumulated_credit is just the intermediate rolls (no final option cash flow):
   ```python
   return child, False, depth + 1, accumulated_credit
   ```

5. At the call site, replace bare `net_credit` with `net_credit + extra_credit`:
   ```python
   terminal_child, chain_open, chain_depth, extra_credit = _resolve_chain(rec_id)
   ...
   if net_credit is not None:
       actual_r = (base_r + (net_credit + extra_credit) / nav) if base_r is not None else None
   ```

6. `chain_open` must be `True` whenever any intermediate hop lacks an execution record, because actual cash flows can't be confirmed.

## Touches

- `agents/outcome_evaluator.py` — `_resolve_chain()` inner function and its call site
- `agent_db.py` — verify `get_executions_for_rec()` and `aggregate_executions()` are accessible without circular import (they are already imported)
- `tests/test_lifecycle.py` — lifecycle test: 2-hop ROLL → BTC chain accumulates all three cash flows into a single `actual_return`

## Done when

- [ ] `_resolve_chain()` accumulates intermediate STO − BTC credits at each roll hop
- [ ] Terminal BTC cash flow is subtracted from cumulative credit
- [ ] Root `actual_r` includes full chain net credit, not just root hop's
- [ ] Chain with any missing execution record stays `actual_is_estimated = True`
- [ ] Lifecycle test: 2-hop chain produces correct `actual_return` matching manual sum
- [ ] All existing tests pass
