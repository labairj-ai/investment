# Dynamic NO_ACTION State Hashes

- **ID:** 0093
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** low
- **Depends:** 0087, 0088

## Problem

`_AGENT_HASH_EXTRAS` in `orchestrator.py` adds config-level constants (thresholds, prompt versions) to the NO_ACTION hash, which invalidates hashes when configuration changes. But it doesn't capture the observable state that drove the agent's NO_ACTION conclusion. For a CC agent: the same config, same price, same thesis version, but IV dropped from 45% to 12% — the hash is the same and no new NO_ACTION row is written. For Tax: lots and holding periods change constantly and should refresh the hash without changing config.

## Proposed approach

Extend `_record_no_actions()` in `orchestrator.py` to include bucketed observable state in the hash:

- **Covered call agent:**
  - `iv_bucket`: round IV to nearest 5% (e.g., 47% → 45)
  - `spread_bucket`: round spread_pct to nearest 2% (e.g., 3.8% → 4)
  - `earnings_bucket`: "inside_contract" / "outside_contract" / "unknown" relative to current contract window
  - `open_cc`: bool — does an open CC exist for the ticker right now?
  - `shares_bucket`: round shares to nearest 50 (e.g., 112 → 100)

- **Tax agent:**
  - `lt_lots_count`: number of lots that crossed long-term threshold in last 30 days
  - `realized_gain_bucket`: round YTD realized gain to nearest $500

- **Portfolio guardian:**
  - `max_weight_bucket`: round max single-position weight to nearest 0.5%
  - `layer_drift_flag`: bool — any layer > target+5%?

These state inputs are fetched from the DB or snapshot inside `_record_no_actions()` and mixed into the hash before calling `compute_agent_hash()`. Bucketing ensures minor price/IV moves don't constantly generate new rows while meaningful state changes do.

## Touches

- `agents/orchestrator.py` — `_record_no_actions()`, `_AGENT_HASH_EXTRAS`
- `agent_db.py` — helpers to fetch latest option snapshot IV + spread for a ticker (already exists via `get_latest_option_snapshot`)
- `agents/covered_call_agent.py` — expose state inputs if not already accessible from snapshot
- `tests/test_lifecycle.py` — test: CC agent NO_ACTION with IV=45 vs IV=12 produces different hashes

## Done when

- [ ] CC NO_ACTION hash changes when IV bucket changes (e.g., 45% → 10%)
- [ ] CC NO_ACTION hash changes when an open CC opens or closes
- [ ] Tax NO_ACTION hash changes when a lot crosses LT threshold
- [ ] Guardian NO_ACTION hash changes when max weight crosses a bucket boundary
- [ ] Bucketing is applied: minor intraday price moves do not create new NO_ACTION rows
