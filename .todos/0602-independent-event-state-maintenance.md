# Decouple Event-State Sweep from Extraction Pipeline

- **ID:** 0602
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** high
- **Depends:** 0598

## Problem

`update_event_state_sweep()` only runs when `run_pipeline()` reaches the end of a successful extraction. When extraction yields zero events the function is skipped entirely. When `generate_news_summaries()` returns early (no holdings with news at all) the sweep is never called. Those are precisely the days where absence of new coverage is supposed to advance FADING and RESOLVED state — the sweep's core purpose. A separate semantic issue: the current RESOLVED state means "no supporting news for ≥30 days," not "the underlying business issue is resolved." A lawsuit can drop out of headlines for a month while the case is still open. RESOLVED as currently implemented silently overstates resolution confidence.

## Proposed approach

- Extract `update_event_state_sweep()` into a standalone daily maintenance function that runs unconditionally — regardless of whether news was fetched, the LLM succeeded, or events were extracted. Wire it beside other nightly maintenance jobs (e.g. the outcome labeling sweep). A simple cron/systemd approach is fine.
- Keep the call inside `run_pipeline()` as well for convenience, but the standalone path must not depend on the pipeline succeeding.
- Add a comment block above the RESOLVED transition in `update_event_state_sweep()` that states explicitly: "RESOLVED here means no new evidence for >{threshold} days, not that the underlying investment issue is resolved. Events involving ongoing legal, regulatory, or structural risks should be treated as STALE rather than RESOLVED until a confirming-resolution event is observed." No state-enum expansion required now — just document the current semantics clearly.
- Optionally: introduce a STALE state (between FADING and RESOLVED) as a named concept even if not implemented yet, so future work has a hook.

## Touches

- `portfolio_ai.py` or a new `agents/news/maintenance.py` — standalone sweep entry point
- `agents/news/intelligence.py` — `update_event_state_sweep()` semantics comment; RESOLVED threshold constant
- Deployment config (systemd timer or cron on optiplex) — daily sweep schedule
- `tests/test_news_intelligence.py` — test that sweep advances state even when no events were extracted today

## Done when

- [x] `update_event_state_sweep()` (or a wrapper) can be called standalone without running `run_pipeline()`
- [x] A day with zero news or failed extraction still advances FADING/RESOLVED state for previously active events
- [x] Code comment on RESOLVED explicitly states the "no evidence for N days" interpretation, not business resolution
- [x] Test: insert event 20 days ago, call sweep with no new events today, confirm FADING state set
