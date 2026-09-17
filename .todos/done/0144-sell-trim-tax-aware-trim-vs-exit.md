# Tax-Aware TRIM vs EXIT: Delay Exit for Near-LT Positions

- **ID:** 0144
- **Status:** done
- **Created:** 2026-09-11
- **Priority:** normal
- **Depends:** none

## Problem

The Sell/Trim agent computes `_tax_note()` (informational only, never feeds into SellStrength) but takes no action based on it. There is a specific high-value scenario that goes unaddressed: a position that scores EXIT (ss ≥ 68) but holds mostly short-term lots that are within ~45 days of crossing the 365-day long-term threshold. In that case, holding 45 more days converts a ~37% ST rate to a ~15% LT rate — a 22-point tax saving on what could be a large gain. The agent should flag this and prefer TRIM over EXIT (to reduce exposure now) when the remaining ST gain is large and the LT crossover is imminent.

## Proposed approach

After computing `action` from SellStrength, check tax lot status:
1. Fetch `near_lt_count = agent_db.get_near_lt_lots_count(ticker, within_days=45)`
2. Fetch `unrealised_gain = agent_db.get_unrealized_gain(ticker)`
3. If `action == "EXIT"` AND `near_lt_count > 0` AND `unrealised_gain > 10_000`:
   - Downgrade action to `"TRIM"` with trim_fraction 0.5 (or scaled)
   - Set `action_payload["tax_deferral_override"] = True`, `"days_to_lt_crossover": ...`
   - Add a note to the LLM prompt and summary explaining the override
4. Do NOT apply this override when a critical pillar is violated (0143's hard EXIT takes precedence)

The `get_near_lt_lots_count(within_days=45)` helper already exists in `agent_db.py` (line ~1107).

## Touches

- `agents/sell_trim_agent.py` — post-scoring section in `_run()`, after `action` is determined
- `agent_db.py` — `get_near_lt_lots_count()` already exists (no change needed)

## Done when

- [ ] EXIT → TRIM when near_lt_count > 0 AND unrealised_gain > $10k AND no critical violation
- [ ] `action_payload["tax_deferral_override"]` is True in that case
- [ ] Critical pillar violation bypasses the tax override (EXIT takes precedence)
- [ ] Existing tests pass
