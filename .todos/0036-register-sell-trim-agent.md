# Register sell_trim_agent and Harden Orchestrator Registry

- **ID:** 0036
- **Status:** backlog
- **Created:** 2026-09-06
- **Priority:** high
- **Depends:** none

## Problem

`sell_trim_agent.py` correctly calls `register_agent("sell_trim", _run)` at the bottom of the file, but `agents/__init__.py` never imports it, so the module never executes and the handler is never registered. `AGENT_ORDER` in `orchestrator.py` lists `sell_trim`, but the orchestrator silently skips any agent whose handler is `None`. This means the Sell/Trim agent may never run at all in production. Silent skipping is also dangerous — if any other triggered agent is unregistered, the orchestrator drops it without warning.

## Proposed approach

- Add `from . import sell_trim_agent` to `agents/__init__.py` alongside the other agent imports.
- Change the `if handler is None: continue` guard in `orchestrator.run_agents()` to raise `RuntimeError(f"Triggered agent {agent_type!r} is not registered")` so missing handlers are immediately visible.
- Add `sell_trim` to `__all__` in `agents/__init__.py` if appropriate.
- Verify no other registered agents are missing from `__init__.py` imports.

## Touches

- `agents/__init__.py`
- `agents/orchestrator.py`

## Done when

- [ ] `from agents import sell_trim_agent` succeeds and `_registry["sell_trim"]` is populated at startup
- [ ] Manually calling `run_agents(snapshot, ["sell_trim"])` produces recommendations (not a silent skip)
- [ ] Calling `run_agents(snapshot, ["nonexistent_agent"])` raises `RuntimeError`
- [ ] All agents in `AGENT_ORDER` have a corresponding import in `__init__.py`
