# Make Capability and Freshness State Real

- **ID:** 0627
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** normal
- **Depends:** 0619

## Problem

Four integration areas are collected by `build_portfolio_brief_state()` but not surfaced in the briefing: macro state is queried and discarded (not included in the returned dict); `learning_state` and `execution_state` are returned but `_build_brief_prompt()` never meaningfully uses either. This means the Decision Brief never tells the user things like "News Intelligence v2 is CALIBRATING with 18 accepted events," "UNP TRIM is already in PENDING_SUBMIT," or "Macro is observe-only and must not influence recommendations."

Freshness also has a semantic problem: `no current recommendations` returns `recommendations = UNAVAILABLE` and `no recent findings` returns `agent_findings = UNAVAILABLE`, making overall freshness DEGRADED when agents ran successfully and simply found nothing. Additionally, `_freshness_entry()` returns `CURRENT` on timestamp parse errors — fail-open when it should fail-closed.

## Proposed approach

- **Add `macro_state` to returned brief state dict.** It is already queried; it just needs to be included in the output under `macro_state`.
- **Deterministic capability summaries:** Have the aggregator turn raw learning/execution/macro data into human-readable state blocks before they reach the LLM prompt:
  ```
  learning:
    News v2 — COLLECTING, 18 accepted events, observe-only
    Macro experiment — Stage 0, production influence 0

  execution:
    UNP TRIM — awaiting user approval
    RIVN — paper order filled
    External broker activity — none

  macro:
    Portfolio exposure — rates elevated
    No production recommendation influence
  ```
  These blocks are passed to the LLM in the prompt so it can summarize them. Do not pass raw data rows.
- **Freshness semantics fix:** Freshness measures subsystem run recency, not content presence. Sources: latest completed Guardian run, latest completed producer pipeline, latest successful news snapshot, latest macro score run, latest learning sweep, latest execution reconciliation. `0 findings` is content state, not a freshness signal.
- **Fail-closed timestamps:** `_freshness_entry()` on parse error returns `UNKNOWN` (treated as DEGRADED), not `CURRENT`.

## Touches

- `portfolio_ai.py` — add `macro_state` to `build_portfolio_brief_state()` return dict; capability summary formatters for learning/execution/macro; freshness source switch from content-presence to run-recency; `_freshness_entry()` fail-closed fix
- `agents/briefing_agent.py` — `_build_brief_prompt()` consumes capability summary blocks
- `generate_dashboard.py` — evidence footer may surface calibration state and execution lifecycle
- `tests/` — test that `macro_state` is present in output; test freshness with zero findings but recent run = CURRENT; test parse error = UNKNOWN

## Done when

- [ ] `build_portfolio_brief_state()` return dict includes `macro_state`
- [ ] `_build_brief_prompt()` includes formatted learning, execution, and macro capability summaries
- [ ] The Decision Brief can surface "News v2 CALIBRATING / observe-only" and "UNP TRIM awaiting approval"
- [ ] Freshness is computed from latest completed subsystem runs, not from whether content was produced
- [ ] Zero findings with a recent run = CURRENT freshness for that source
- [ ] `_freshness_entry()` timestamp parse error returns UNKNOWN/DEGRADED, not CURRENT
- [ ] Test: agent ran 30 min ago with 0 findings → `agent_findings = CURRENT`
- [ ] Test: `_freshness_entry()` with unparseable timestamp → UNKNOWN
