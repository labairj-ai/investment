# Build Deterministic Portfolio Brief State Aggregator

- **ID:** 0619
- **Status:** done
- **Created:** 2026-09-24
- **Priority:** high
- **Depends:** 0618

## Problem

`generate_daily_insight()` and `briefing_agent.py` both independently collect and prioritize the same raw data, making them redundant and creating a circular dependency (Briefing Agent reads the cached AI insight for macro context; AI insight includes briefing output). Neither has a complete picture: thesis health, accepted News v2 signals, learning calibration state, execution lifecycle, and data freshness are all absent or only partially represented. The LLM ends up being asked to discover priorities from raw prose instead of reasoning over a structured state summary.

## Proposed approach

Build `build_portfolio_brief_state(conn, now=None) -> dict` — a single deterministic function with no LLM calls that collects every subsystem into one timestamped object. This becomes the sole input to the Briefing Agent (0620) and the stored snapshot for delta computation (0622) and provenance (0623).

Collect in one pass:
- **Producer findings:** open Sell/Trim, Covered Call, Opportunity Hunter, Tax recommendations with Critic verdict (APPROVED / CHALLENGED / REJECTED) and lifecycle state (recommended → approved → intent → filled)
- **Guardian state:** active findings by type (`position_risk`, `risk_contribution`, `policy_breach`); policy violations (size, layer drift, cash floor, concentration, drawdown, daily loss)
- **Thesis Monitor:** per-holding health scores with delta from previous brief; newly WARNING/VIOLATED pillars; trigger proximity (review/trim/exit); pending required reviews
- **Accepted News v2:** `get_accepted_news_events()` filtered to current signals, structured by ticker with `event_type`, `confirmation_level`, `thesis_relevance`; portfolio themes; grounding-degraded tickers flagged
- **Macro state:** current scores with `scored_at_epoch`; whether within accepted calibration window
- **Learning state:** accepted event count, unique decision dates, per-agent confidence tier (HIGH / OBSERVE_ONLY / CALIBRATING), last sweep results
- **Execution state:** open intents by status, paper fills since last brief, broker activity flags
- **Freshness:** per-source `last_updated`, staleness flags, degraded systems, news intelligence version + calibration status, watchdog overall

Also compute `changes` by diffing against the most recently stored brief snapshot (or return empty list if none exists).

Output schema (all deterministic — no generated text):
```json
{
  "captured_at": ...,
  "changes": [],
  "attention_items": [],
  "opportunities": [],
  "watch_items": [],
  "open_decisions": [],
  "thesis_deltas": [],
  "news_signals": [],
  "portfolio_risks": [],
  "critic_summary": {},
  "learning_state": {},
  "execution_state": {},
  "freshness": {}
}
```

Store the output in a `portfolio_brief_snapshots` table (keyed by `captured_at`) so delta computation in 0622 has a history to diff against.

## Touches

- `portfolio_ai.py` — new `build_portfolio_brief_state()` function; `_init_ai_tables()` migration for `portfolio_brief_snapshots`
- `agents/news/intelligence.py` — `get_accepted_news_events()` already exists (0618)
- Possibly a new `briefing_state.py` module if `portfolio_ai.py` becomes too large
- `tests/` — unit tests for the aggregator with a seeded DB

## Done when

- [ ] `build_portfolio_brief_state(conn)` returns a fully populated dict with all 12 top-level keys
- [ ] All fields are sourced deterministically (no LLM calls, no network calls inside the function)
- [ ] Result includes `changes` array populated by diff against last stored snapshot (empty if none)
- [ ] Output is stored in `portfolio_brief_snapshots` table on each call
- [ ] `freshness` block reflects real per-source staleness, not a fixed string
- [ ] Tests cover: empty DB returns a valid skeleton; seeded DB returns correct attention/opportunity/watch classification
