# Move CC Tax Constants Out of covered_call_rec into strategy_config

- **ID:** 0159
- **Status:** done
- **Created:** 2026-09-12
- **Priority:** normal
- **Depends:** 0157

## Problem

`covered_call_rec.py` hardcodes three tax-related constants:
```python
_TAX_ST_RATE = 0.37
_TAX_LT_RATE = 0.20
_LOT_TAX_FRICTION_THRESHOLD = 500
```

`TAX_ST_RATE` and `TAX_LT_RATE` already live in `strategy_config.py` (loaded from config JSON, imported by `tax_agent.py`). Duplicating them in the CC module creates a divergence risk: if the user changes their tax bracket in config, the CC management decision won't reflect it. The $500 friction threshold is a user strategy assumption, not an option-pricing constant — it belongs with the other thresholds in config too.

## Proposed approach

1. Remove `_TAX_ST_RATE`, `_TAX_LT_RATE` from `covered_call_rec.py`; import `TAX_ST_RATE`, `TAX_LT_RATE` from `strategy_config` (already defined there).
2. Add `cc_assignment_tax_friction_threshold: float = 500` to `strategy_config.py` (and the underlying config JSON schema), so it is user-configurable.
3. `_lot_tax_friction()` reads the threshold from `strategy_config.cc_assignment_tax_friction_threshold`.

This makes CC management ask the tax subsystem "what is the avoidable tax?" using the same rates the rest of the application uses.

## Touches

- `covered_call_rec.py` — remove `_TAX_ST_RATE`, `_TAX_LT_RATE`, `_LOT_TAX_FRICTION_THRESHOLD`; add `from strategy_config import TAX_ST_RATE, TAX_LT_RATE, cc_assignment_tax_friction_threshold` (or equivalent)
- `strategy_config.py` — add `cc_assignment_tax_friction_threshold` loaded from config JSON with default 500
- Config JSON schema (if documented) — add the new key
- `tests/` — ensure `_lot_tax_friction` still produces correct values after constant migration

## Done when

- [ ] `covered_call_rec.py` no longer defines its own ST/LT rate constants
- [ ] `strategy_config` exports `cc_assignment_tax_friction_threshold` (default 500)
- [ ] Changing `st_tax_rate` in config affects both `tax_agent` and CC assignment friction
- [ ] Existing tests pass
