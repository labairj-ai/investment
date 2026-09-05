# Centralize Strategy Configuration into Single Source of Truth

- **ID:** 0001
- **Status:** done
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

## Outcome

Created `config/strategy.json` (layers 1–5 with name, description, target_pct, color; covered_calls block with all CC params; risk block with drift_threshold, gross_dom limits) and `strategy_config.py` (thin loader exposing typed constants).

All four files migrated:
- `portfolio_ai.py` — removed local `LAYER_NAMES` and inline `TARGETS` dict; added `_LAYER_NAMES_LONG` for AI prompt framework text; `DRIFT_THRESHOLD` now from config
- `generate_dashboard.py` — removed `LAYER_NAMES`/`LAYER_LABELS` definitions; replaced `layer_targets.json` file read with `LAYER_TARGETS` dict
- `send_newsletter_main.py` — removed `LAYER_NAMES`, `LAYER_COLORS`, `LAYER_TARGETS_DEFAULT`, `LAYER_TARGETS_F`, `DRIFT_THRESHOLD`, `LAYER_GROSS_DOM`, `HOLDING_GROSS_DOM`, and `load_layer_targets()` function; fixed the stale fallback targets (L1 was 25→33, L3 was 35→29, L4 was 12→10)
- `covered_call_rec.py` — all CC settings (`MIN_DTE`, `MAX_DTE`, `MAX_DTE_EXTENDED`, `R_MIN`, `R_FORWARD`, `EXEC_LAMBDA`, `MIN_BID`, `TOP_N`, `MAX_STRIKE_MULTIPLIER`) now imported from `strategy_config`

`layer_targets.json` deleted.

Note for next items: `generate_dashboard 2.py` (a backup file, not a live script) still references `layer_targets.json`. The JS `ALLOC_META` and `LAYER_META` objects in the dashboard HTML template still hardcode layer names and colors — they cannot import Python. They don't contain target numbers so the Done-when check passes, but colors/names could drift. Consider injecting them from `strategy_config` data via the chart_data JSON in a future pass.

## Done when

- [x] Single `config/strategy.json` defines all layer targets, CC params, risk thresholds
- [x] `portfolio_ai.py`, `generate_dashboard.py`, `send_newsletter_main.py` all import from `strategy_config` — no duplicated layer definitions remain
- [x] `layer_targets.json` is retired; dashboard JS reads targets from the same injected data as today but sourced from `strategy_config`
- [x] `grep -r "target_pct\|35\|22\|29\|33\|20" *.py` returns no hardcoded allocation numbers outside `strategy_config`
