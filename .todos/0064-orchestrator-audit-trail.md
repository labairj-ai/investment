# Orchestrator: Populate Audit Trail in agent_runs

- **ID:** 0064
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** P1
- **Depends:** none

## Problem

`agent_runs` has excellent schema fields — `trigger_type`, `trigger_key`, `model`, `prompt_version`, `input_hash`, `input_snapshot_json` — but `_run_single_agent()` calls:

```python
agent_db.insert_agent_run(agent_type=agent_type, scope="portfolio", ticker=ticker)
```

leaving all audit fields as NULL. Six months from now, you cannot answer: "Why did the agent make recommendation #472? What model, what snapshot, what trigger?"

## Proposed approach

### 1. Pass trigger_type and trigger_key from the TriggerEvent

```python
run_id = agent_db.insert_agent_run(
    agent_type=agent_type,
    scope="portfolio",
    ticker=ticker,
    trigger_type=primary_trigger,
    trigger_key=primary_trigger_key,   # e.g. ticker or event ID
    model=_current_model_id(),         # read from ollama_client or env
)
```

### 2. Compute and store input_hash

Use the existing `agent_db.compute_input_hash()` function. Call it at the start of each agent run using the snapshot data for the relevant ticker:

```python
thesis_ver = agent_db._get_thesis_version_for_hash(ticker)
latest_q   = agent_db._get_latest_quarter_for_hash(ticker)
input_hash = agent_db.compute_input_hash(
    ticker, agent_type,
    snapshot_holding.current_price,
    thesis_ver, latest_q,
)
```

### 3. Serialize snapshot for input_snapshot_json

Pass a compact snapshot dict (not the full JSON of all holdings) to avoid bloat. For per-ticker agents, serialize only the relevant holding. For portfolio-scope agents, serialize summary stats (total_value, layer_weights, holding count):

```python
input_snapshot = {
    "ticker": ticker,
    "price": holding.current_price,
    "shares": holding.shares,
    "weight_pct": holding.weight_pct,
    "price_as_of": snapshot.price_as_of,
    "total_value": snapshot.total_value,
}
```

### 4. Add prompt_version constants to each agent

Each agent module defines a module-level constant:

```python
_PROMPT_VERSION = "sell_trim_v2"  # bump when the LLM prompt text changes
```

Pass to `insert_agent_run(prompt_version=_PROMPT_VERSION)`.

### 5. Model ID helper

Add `get_model_id() -> str` to `ollama_client.py` that returns the current model name from the LLM_URL or env config. Pass to `insert_agent_run(model=get_model_id())`.

## Touches

- `agents/orchestrator.py` — `_run_single_agent()` passes all audit fields
- `agent_db.py` — `insert_agent_run()` signature already accepts these; just need callers to pass them
- `ollama_client.py` — add `get_model_id()` helper
- Each agent module — add `_PROMPT_VERSION` constant

## Done when

- [ ] `agent_runs` rows have non-NULL `trigger_type` after a pipeline run
- [ ] `agent_runs` rows have non-NULL `input_hash` for per-ticker agents
- [ ] `agent_runs` rows have non-NULL `model` after a pipeline run
- [ ] `agent_runs` rows have non-NULL `prompt_version` for at least sell_trim and covered_call agents
- [ ] `input_snapshot_json` contains compact snapshot for the evaluated ticker
- [ ] **Backend QA:** run pipeline on optiplex; inspect agent_runs table; confirm fields populated
- [ ] **No service regression:** investment service running normally
