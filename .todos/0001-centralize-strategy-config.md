# Centralize Strategy Configuration into Single Source of Truth

- **ID:** 0001
- **Status:** backlog
- **Created:** 2026-09-05
- **Priority:** high
- **Depends:** none

## Problem

Layer targets, CC parameters, and risk thresholds are currently duplicated across at least four places: `portfolio_ai.py` (LAYER_NAMES + TARGETS dict), `generate_dashboard.py` (ALLOC_META + inline target values), `send_newsletter_main.py` (layer descriptions), and `layer_targets.json`. When a value is changed in one place (as happened with the 105→100% fix on 2026-09-05), the others must be updated manually and can drift. Once agents start reading config to make decisions, inconsistency between sources becomes a correctness bug, not just a maintenance annoyance.

## Proposed approach

- Create `strategy_config.py` at the repo root that loads from `config/strategy.json` (or is itself the canonical definition).
- Schema covers: layers (name, short_name, target_pct, color, description), covered_calls (min_dte, max_dte, min_profit_pct), risk (layer_drift_warning_pct, max_single_position_pct).
- Every other file imports from `strategy_config` — no hardcoded layer names or targets elsewhere.
- Delete `layer_targets.json` once `generate_dashboard.py` reads from `strategy_config`.
- Open question: JSON file (easy to edit by hand, readable by JS) vs pure Python module (type-safe, importable). Probably JSON loaded by a thin Python wrapper so both Python and the dashboard JS can use it.

## Touches

`strategy_config.py` (new), `config/strategy.json` (new), `portfolio_ai.py`, `generate_dashboard.py`, `send_newsletter_main.py`, `layer_targets.json` (delete after migration), `covered_call_rec.py` (if it hardcodes CC params)

## Done when

- [ ] Single `config/strategy.json` defines all layer targets, CC params, risk thresholds
- [ ] `portfolio_ai.py`, `generate_dashboard.py`, `send_newsletter_main.py` all import from `strategy_config` — no duplicated layer definitions remain
- [ ] `layer_targets.json` is retired; dashboard JS reads targets from the same injected data as today but sourced from `strategy_config`
- [ ] `grep -r "target_pct\|35\|22\|29\|33\|20" *.py` returns no hardcoded allocation numbers outside `strategy_config`
