# Migrate All LT/ST Date Logic to Canonical tax_utils

- **ID:** 0166
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0165

## Problem

After `tax_utils.py` is created (0165), six files still contain inline LT/ST date arithmetic that must be replaced. Until all call sites are migrated there will be two sources of truth for "long-term" status, and discrepancies near anniversary dates will persist across the tax agent, trigger system, CC assignment engine, and sell tracker.

## Proposed approach

Replace each inline expression with the appropriate `tax_utils` function:

- `covered_call_rec.py:914,934` — replace `lt_cutoff = today - timedelta(days=365)` with `is_long_term(purchase_date, today)` check; replace `timedelta(days=365) - (today - purchase_date)` with `days_until_lt(purchase_date, today)`
- `agent_db.py:1060,1122` — replace `timedelta(days=365)` string comparison in `get_lt_lots_count` with a Python-side filter using `is_long_term()`
- `agents/tax_agent.py:244` — replace `lt_date = purchase + timedelta(days=365)` with `lt_threshold(purchase)`; replace `days_to_lt` derivation with `days_until_lt(purchase, today)`
- `agents/triggers.py:308` — same replacement as tax_agent
- `portfolio_ai.py:569,600` — replace `lt_date = oldest_date + timedelta(days=365)` with `lt_threshold(oldest_date)`
- `serve.py:437-440` — replace inline `replace(year+1)` + `ValueError` guard with `is_long_term(purchase_dt, sell_dt)`

The functional change is only visible on lots purchased on Feb 29 or whose anniversary falls exactly on the cutoff date. All existing tests should pass unchanged.

## Touches

- `covered_call_rec.py`
- `agent_db.py`
- `agents/tax_agent.py`
- `agents/triggers.py`
- `portfolio_ai.py`
- `serve.py`

## Done when

- [ ] No file outside `tax_utils.py` contains `timedelta(days=365)` for LT/ST classification
- [ ] `serve.py` FIFO allocation uses `is_long_term()` instead of inline replace logic
- [ ] `get_lt_lots_count` in `agent_db.py` uses calendar-correct threshold
- [ ] All existing tests pass
