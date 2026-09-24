# Consolidate Briefing Agent as Sole Synthesis Engine

- **ID:** 0620
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0619

## Problem

There are currently two independent portfolio-level synthesis paths: `generate_daily_insight()` in `portfolio_ai.py` runs as part of `generate_news_summaries()` and produces a standalone AI insight, while `briefing_agent.py` runs after producer agents and the Critic and generates a separate BRIEFING recommendation. The Briefing Agent reads the cached AI insight for macro context, creating a circular dependency: AI insight → Briefing Agent → AI insight. The correct direction is canonical evidence → Briefing Agent → dashboard, with `generate_daily_insight()` either retired or reduced to a thin wrapper.

## Proposed approach

- **Remove the circular input:** Delete the Briefing Agent's dependency on `cached_insight.macro_summary` (or any field from the AI Portfolio Insight cache). Replace it with the `macro_state` block from the Portfolio Brief State (0619).
- **Make BriefingAgent consume Portfolio Brief State exclusively:** Pass `build_portfolio_brief_state(conn)` output as the primary input to `run_briefing_agent()`. The LLM receives a structured object and is asked to summarize/explain it — not to discover priorities.
- **Upgrade the Briefing Agent output schema** from the current minimal `{"summary": "...", "key_tickers": []}` to a richer structured result:
  ```json
  {
    "headline": "...",
    "what_changed": [],
    "needs_attention": [],
    "opportunities": [],
    "watch": [],
    "key_question": "...",
    "portfolio_state": "STABLE | ATTENTION | URGENT",
    "source_refs": []
  }
  ```
- **Retire `generate_daily_insight()` as an independent reasoning path:** Stop calling it as a second synthesis system. Options: (a) delete it and redirect callers to the briefing result; (b) turn it into a thin compatibility shim that returns the briefing headline + summary so any existing dashboard code reading `cached_insight` doesn't break immediately. Do not keep two separate LLM synthesis calls that reason over the same portfolio state.
- **Update `serve.py` pipeline:** Ensure the briefing agent runs after producers + Critic, consumes Portfolio Brief State, and its output is what the dashboard's Portfolio Decision Brief card reads. Remove any path that passes old `cached_insight` fields into the briefing prompt.

## Touches

- `agents/briefing_agent.py` — remove `cached_insight` dependency; accept Portfolio Brief State input; upgrade output schema
- `portfolio_ai.py` — `generate_daily_insight()` retirement or shim; `generate_news_summaries()` may need to stop triggering its own briefing
- `serve.py` — pipeline ordering; which result the `/api/watchdog` and dashboard endpoints serve as the briefing
- `tests/` — briefing agent tests with the new input contract

## Done when

- [ ] `briefing_agent.py` no longer reads from any cached AI insight field
- [ ] Briefing Agent input is the Portfolio Brief State dict from `build_portfolio_brief_state()`
- [ ] Briefing Agent output includes `headline`, `what_changed`, `needs_attention`, `opportunities`, `watch`, `key_question`, `portfolio_state`, `source_refs`
- [ ] `generate_daily_insight()` is either deleted or produces output by forwarding the briefing result (not by making an independent LLM call)
- [ ] No circular dependency: the briefing does not read its own prior output as input
- [ ] Pipeline runs briefing after producers + Critic, not as a side effect of news summarization
