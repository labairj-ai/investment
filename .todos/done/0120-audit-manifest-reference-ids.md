# Enrich Agent-Run Audit Manifest with Reference IDs

- **ID:** 0120
- **Status:** backlog
- **Created:** 2026-09-07
- **Priority:** normal
- **Depends:** 0078

## Problem

The current `input_snapshot_json` stored in `agent_runs` captures per-ticker scalars (price, shares, weight, thesis_version, financial_period, macro_as_of, financials_as_of, prompt_version, model). A recommendation may additionally depend on:

- The specific option quote snapshot used (IV, spread, mark)
- The specific earnings event used
- The strategy config state at run time
- The specific financial data snapshot hash

Without these reference IDs, the audit trail cannot answer: "Given the same inputs, would this agent produce the same recommendation today?" The existing `input_hash` is a scalar fingerprint but provides no path back to the source data.

## Proposed approach

Add the following keys to `_input_snap` in `orchestrator.py` when the data is available:

```python
{
  "option_snapshot_id": <int | None>,   # latest agent_db.get_latest_option_snapshot(ticker).id
  "earnings_event_id":  <int | None>,   # latest agent_db.get_latest_earnings_event(ticker).id
  "strategy_config_hash": <str>,        # sha256 of json.dumps(strategy_config.as_dict(), sort_keys=True)
  "financial_snapshot_hash": <str | None>, # sha256 of the financial row used for this ticker
}
```

IDs rather than duplicated data — the referenced rows are already immutable once written. `None` when no snapshot exists (CC/Tax agents that don't use option data need not emit the option field).

The `strategy_config_hash` should be computed once per run session (not per ticker) and cached.

## Touches

- `agents/orchestrator.py` (`_input_snap` dict construction)
- `agent_db.py` (possibly helpers to fetch latest snapshot IDs)
- `strategy_config.py` (add `as_dict()` or equivalent for hashing)
- `tests/test_lifecycle.py` (assert snapshot keys present in agent_runs row)

## Done when

- [ ] `agent_runs.input_snapshot_json` includes `option_snapshot_id` (None when no snapshot)
- [ ] `agent_runs.input_snapshot_json` includes `earnings_event_id` (None when no event)
- [ ] `agent_runs.input_snapshot_json` includes `strategy_config_hash`
- [ ] `agent_runs.input_snapshot_json` includes `financial_snapshot_hash` (None when no financials)
- [ ] A lifecycle test confirms at least `strategy_config_hash` is present in every agent run row
