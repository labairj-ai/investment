# Fix Tax Agent Math: Avoidable Tax and LT Loss Harvesting

- **ID:** 0056
- **Status:** backlog
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

## Done when

- [ ] Avoidable-tax figure in recommendation uses `gain × (ST_rate − LT_rate)`, not `gain × ST_rate`
- [ ] `ST_TAX_RATE` and `LT_TAX_RATE` defined in `strategy_config.py` and imported by tax agent
- [ ] LT lots with unrealized losses appear in TLH recommendations
- [ ] Recommendation text distinguishes ST vs LT loss and explains netting benefit accurately
- [ ] A lot at 95% of LT status with $10k gain: avoidable-tax shown as ~$1,700 (10k × 17pp), not $3,700 (10k × 37%)
- [ ] **Backend QA:** run the feature on production optiplex and confirm expected DB changes appear in `investment.db`
- [ ] **Frontend QA:** dashboard loads without errors; affected UI sections render correctly; no JS console errors; no broken API endpoints
- [ ] **No service regression:** investment service still running; all existing API routes respond correctly after the change
