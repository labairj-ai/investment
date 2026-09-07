# Persist Richer Input Manifest for Agent Run Reproducibility

- **ID:** 0078
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** normal
- **Depends:** none

## Problem

The current `input_snapshot_json` for a ticker agent run stores only `{ticker, price, shares, weight_pct, price_as_of}`. But a recommendation may depend on thesis version, strategy config, financial period, macro scores, option chain IV, earnings date, and existing CC positions — none of which are captured. Six months later it is impossible to reproduce "why did the agent recommend this?" from the stored record alone.

## Proposed approach

- Define a per-agent manifest builder (can live in `agents/orchestrator.py` or a new `agents/manifest.py`) that constructs a structured dict keyed by data source:
  ```json
  {
    "strategy_hash": "sha256 of strategy_config at run time",
    "thesis_version": 3,
    "financial_period": "2026-Q2",
    "financial_data_hash": "sha256 of financials used",
    "macro_as_of": "2026-09-01",
    "macro_hash": "sha256 of macro scores",
    "price_as_of": "2026-09-06",
    "option_chain_as_of": "...",
    "open_cc_id": "...",
    "event_calendar_as_of": "...",
    "prompt_version": "sell_trim_v2",
    "model": "Qwen3.6-35B-A3B-4bit"
  }
  ```
- Store this as `input_snapshot_json` in `agent_runs` (replaces the current minimal dict).
- Each agent handler is responsible for passing the relevant fields to the manifest builder via `AgentContext`.
- Hashes (not raw data) are sufficient for most fields to keep storage size manageable.
- Open question: is a separate `input_manifests` table better than JSON in `agent_runs`? The JSON approach is simpler and sufficient for now.

## Touches

- `agents/orchestrator.py` — manifest construction in `_run_single_agent()`
- `agents/contracts.py` — `AgentContext` may need fields for manifest data
- Each specialist agent — pass relevant context to manifest
- `tests/test_agent_db.py` — verify manifest fields are stored

## Done when

- [ ] `input_snapshot_json` for ticker-scoped agents includes thesis_version, financial_period, macro_as_of, price_as_of, and prompt_version at minimum
- [ ] Strategy config hash included for portfolio-scoped agents
- [ ] Manifests can be read back and decoded without error
- [ ] Test: agent run manifest contains at least the required fields
