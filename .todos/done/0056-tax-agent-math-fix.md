# Fix Tax Agent Math: Avoidable Tax and LT Loss Harvesting

- **ID:** 0056
- **Status:** done
- **Created:** 2026-09-06
- **Priority:** low
- **Depends:** none

## Problem

Two mathematical issues in `tax_agent.py`: (1) For a lot approaching long-term status, the agent reports the full short-term tax cost (`gain × ST_rate`) as "potentially avoidable by waiting." But the relevant incremental friction from selling early is only `gain × (ST_rate − LT_rate)` — selling after crossing LT doesn't make the tax disappear, it just reduces the rate. This overstates the benefit of waiting and can cause misleading recommendations. (2) TLH analysis is limited to short-term lots. Long-term losses are also useful for capital-loss netting (they offset LT gains at the LT rate and can offset ST gains too), so excluding them understates the harvesting opportunity on positions that have been held >1 year.

## Proposed approach

- Fix (1): change the avoidable-tax calculation to `gain × (ST_rate − LT_rate)`. Add explicit `st_tax_rate` and `lt_tax_rate` constants (0.37 and 0.20 as defaults; consider state tax as an optional add-on).
- Fix (2): extend TLH analysis to include long-term lots with unrealized losses. When reporting a TLH opportunity, distinguish:
  - ST loss: can offset ST or LT gains, most flexible
  - LT loss: can offset LT or ST gains (via ordering rules), still valuable
- Update the recommendation text to clearly explain the incremental benefit, not the total tax on an early sale.
- Expose `st_tax_rate` and `lt_tax_rate` in `strategy_config.py` so they can be adjusted without touching agent code.

## Touches

- `agents/tax_agent.py`
- `strategy_config.py` (add `ST_TAX_RATE`, `LT_TAX_RATE` constants)

## Outcome

- **`config/strategy.json`**: Added `lt_tax_rate: 0.20`.
- **`strategy_config.py`**: Exported `TAX_LT_RATE`.
- **`agents/tax_agent.py`**:
  - WAIT logic: `avoidable_tax = gain × (TAX_ST_RATE - TAX_LT_RATE)`. `st_tax_cost` still computed and stored in payload for full transparency. LLM prompt updated to explain the rate differential explicitly.
  - HARVEST logic: removed `if days_held >= 365: continue`. Each lot now tagged `lot_type = "LT"/"ST"`. `benefit_rate = TAX_LT_RATE` for LT losses (offset LT gains) vs `TAX_ST_RATE` for ST losses (offset ST gains). LLM narrative receives `lot_type` param and describes netting accordingly. `why_now` text now includes `(at {benefit_rate} {lot_type} rate)`. `action_payload` includes `lot_type`, `benefit_rate`, `lt_tax_rate`.

## Done when

- [x] Avoidable-tax figure in WAIT recommendation uses `gain × (ST_rate − LT_rate)` = `gain × 17%` — st_tax_cost retained in payload for transparency but not shown as "avoidable"
- [x] `TAX_LT_RATE` added to strategy.json (0.20) and exported from strategy_config.py; imported by tax agent
- [x] LT lots now included in TLH — `if days_held >= 365: continue` removed; `lot_type` tagged as "ST"/"LT"
- [x] HARVEST recommendation text includes lot_type label; LLM prompt distinguishes ST vs LT netting; benefit_rate = LT_TAX_RATE for LT lots
- [x] $10k gain × 17% rate differential = $1,700 avoidable tax (verified by code inspection)
- [x] **Backend QA:** deployed to optiplex — service active
- [x] **Frontend QA:** no UI changes; recommendation text renders correctly in existing DQ card
- [x] **No service regression:** service active after deploy
