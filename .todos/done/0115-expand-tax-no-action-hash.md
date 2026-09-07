# Expand Tax Agent NO ACTION State Hash with Full Lot/Gain Picture

- **ID:** 0115
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0108

## Problem

The Tax agent's NO_ACTION hash (0108) was upgraded to use `get_lt_lots_count` and `get_ytd_realized_gain` from real tables. But it still hashes only two fields: long-term lot count and a combined YTD gain bucket. This means the hash doesn't change when: a short-term lot count changes, a lot is about to cross the LT threshold (a key tax event), or ST vs LT gain composition shifts (which changes the effective tax rate). The NO_ACTION decision can stay stale across meaningful state changes that should trigger fresh agent evaluation.

## Proposed approach

Add these hash fields to the tax branch in `_compute_no_action_state_extras()`:
- `st_lots_count` — count of open lots held < 365 days
- `near_lt_lots_count` — lots that will cross LT threshold within 45 days
- `ytd_st_gain_bucket` — YTD ST realized gains from `sell_transactions.st_gain`, bucketed to nearest $500
- `ytd_lt_gain_bucket` — YTD LT realized gains from `sell_transactions.lt_gain`, bucketed to nearest $500
- `unrealized_gain_bucket` — sum of unrealized gain (can be negative = loss) from `cost_lots` vs latest `holding_day` price, bucketed to nearest $500

Add corresponding helpers to `agent_db.py`:
- `get_st_lots_count(ticker)` — WHERE purchase_date > today−365d
- `get_near_lt_lots_count(ticker, within_days=45)` — WHERE purchase_date BETWEEN today−365d+1d AND today−365d+within_days
- `get_ytd_st_realized_gain(ticker)` — SUM(st_gain) WHERE sell_date >= year-start
- `get_ytd_lt_realized_gain(ticker)` — SUM(lt_gain) WHERE sell_date >= year-start
- `get_unrealized_gain(ticker)` — sums (current_price − cost_per_share) × shares across cost_lots; returns 0.0 on missing table

Replace the old `realized_gain_bucket` (combined) with the two split fields.

## Touches

- `agent_db.py`
- `agents/orchestrator.py`
- `tests/test_agent_db.py` (new helper tests)

## Done when

- [ ] Tax hash includes st/lt lot counts, near-LT count, split ST/LT gain buckets, unrealized gain bucket
- [ ] Old combined `realized_gain_bucket` removed from tax hash
- [ ] All new agent_db helpers return 0/0.0 gracefully when tables are absent
- [ ] Tests cover each new helper
