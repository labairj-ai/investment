# Tax Agent: HARVEST Misses LT Loss vs LT Gain Scenario

- **ID:** 0150
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** high
- **Depends:** none

## Problem

`_check_tlh()` in `agents/tax_agent.py` gates on `ytd_st_gains <= 0: return []`. This completely skips all HARVEST recommendations when there are no short-term realized gains — even when there are large long-term realized gains that LT losses can directly offset.

Example: investor sold BRK-B for a $40,000 LT gain and holds JOBY with a $15,000 LT unrealized loss. LT loss offsets LT gain → saves $2,250 (15% × $15,000). The current agent produces no recommendation.

The agent's own narrative template acknowledges "LT loss (offsets LT gains at LT rate)" but the entry gate blocks the code path entirely.

## Proposed approach

1. Add a separate `ytd_lt_gains()` query (same as `_ytd_st_gains()` but reading `lt_gain` from `sell_transactions`).
2. Change the gate to: `if ytd_st_gains + ytd_lt_gains <= 0: return []`
3. In `_check_tlh()`, pass `ytd_lt_gains` alongside `ytd_st_gains`.
4. In the lot evaluation, use the appropriate rate and gains offset:
   - ST lots: offset against `ytd_st_gains` at `TAX_ST_RATE`
   - LT lots: offset against `ytd_lt_gains` at `TAX_LT_RATE` first; remainder against `ytd_st_gains` at `TAX_ST_RATE` (but LT loss can also offset ST gains at a higher effective rate, so use the higher of the two)
5. Update `why_now` and LLM prompt to correctly describe which gains are being offset.
6. `agent_db.get_ytd_lt_realized_gain()` helper already exists (0115) — no new DB changes.

## Touches

- `agents/tax_agent.py` — `_check_tlh()` gate + lot evaluation + harvest benefit calculation
- `_ytd_lt_gains()` local helper or call `agent_db.get_ytd_lt_realized_gain()`

## Done when

- [ ] LT lot with loss + LT realized gains triggers HARVEST recommendation
- [ ] ST lot with loss + ST realized gains still triggers HARVEST (unchanged behavior)
- [ ] LT loss / LT gain benefit correctly uses TAX_LT_RATE
- [ ] Existing tests pass
