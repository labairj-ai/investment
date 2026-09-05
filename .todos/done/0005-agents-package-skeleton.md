# Create agents/ Package Skeleton with Shared Contracts

- **ID:** 0005
- **Status:** done
- **Created:** 2026-09-05
- **Priority:** high
- **Depends:** 0004

## Problem

Before any individual agent can be built, there needs to be a shared type system, an orchestrator entry point, and a common pattern for how agents receive context and return findings. Without this skeleton, each agent will invent its own conventions and the orchestrator will have nothing to wire them into.

## Proposed approach

Create `agents/` package with these files:

- `__init__.py` — empty or re-exports key types
- `contracts.py` — dataclasses/TypedDicts for: `PortfolioSnapshot`, `AgentContext`, `AgentFinding`, `Recommendation`, `CriticReview`. These are the only types that cross agent boundaries. No business logic here.
- `orchestrator.py` — `run_agents(snapshot, triggered_agents)` function. Acquires LLM semaphore, runs agents in sequence (Guardian → CC → Thesis → Opportunity → Tax → Critic → Briefing), writes results to DB via `agent_db.py`, returns list of recommendations.
- `triggers.py` — `detect_triggers(snapshot) → list[TriggerEvent]`. Pure deterministic function; no LLM calls. Maps trigger conditions (price Z-score, layer drift, CC eligibility, LT lot timing, etc.) to which agent should run.
- `confidence.py` — `calculate_confidence(data_sources, evidence, rule_support) → int`. Implements the D+F+S+A+R formula and confidence caps. No LLM calls.
- `agent_db.py` — thin wrapper around the tables from 0004; handles all inserts, status updates, and queries agents need.

Also create `strategy_config.py` at repo root if 0001 is not yet done (this skeleton needs config access).

LLM semaphore lives in `orchestrator.py`: `_llm_semaphore = threading.Semaphore(1)`.

## Touches

`agents/` (new directory), `agent_db.py` (new), `strategy_config.py` (new or from 0001), `serve.py` (import orchestrator)

## Done when

- [x] `agents/` package importable with no errors
- [x] `contracts.py` defines all shared dataclasses with type annotations
- [x] `triggers.py` `detect_triggers()` runs against a mock snapshot and returns a list (even if empty)
- [x] `confidence.py` `calculate_confidence()` returns a value in 0–100 for a sample input
- [x] `orchestrator.py` `run_agents()` exists and accepts the right signature (even if it's a stub that calls nothing yet)
- [x] `agent_db.py` wraps the tables from 0004
- [x] QA evaluation conducted: functionality verified working, no regressions introduced

## Outcome

Created `agents/` package with five files:

- `contracts.py` — 6 dataclasses (HoldingSnapshot, PortfolioSnapshot, AgentContext, AgentFinding, Recommendation, CriticReview) with full type annotations
- `triggers.py` — TriggerEvent dataclass + `detect_triggers()`: fires layer_drift→portfolio_guardian, cc_eligible→covered_call, portfolio_scope→briefing; verified L1+L5 drift + 2 CC + 1 daily trigger from a mock snapshot
- `confidence.py` — `calculate_confidence()` D+F+S+A+R composite; cap to 60 when price/holdings missing, cap to 70 when rule_support < 0.5; all cap assertions passed
- `orchestrator.py` — `_llm_semaphore = threading.Semaphore(1)`, `AGENT_ORDER`, `register_agent()`, `run_agents()` wired to agent_db; returns [] when no handlers registered
- `__init__.py` — re-exports all 11 public names via `__all__`

agent_db.py was created in 0004 and is already in place. No existing files were modified by this todo. Items 0006, 0007, 0008, 0009, and 0020 are now unblocked.

