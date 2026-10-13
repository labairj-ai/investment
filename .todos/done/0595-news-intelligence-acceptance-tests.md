# News Intelligence Acceptance Test Suite

- **ID:** 0595
- **Status:** done
- **Created:** 2026-09-23
- **Priority:** normal
- **Depends:** 0588, 0589, 0590, 0591, 0592, 0593, 0594

## Problem

Commit 981d78b added approximately 800 lines of logic (hashing, extraction, thesis mapping, trend detection, scoring, confirmation, episode capture) with no tests. All state machine transitions, scoring formulas, and classification rules are untested. Bugs in 0589–0594 were found by code review, not by a failing test. Without a test suite, each hardening pass in 0588–0594 has no way to prove it fixed the intended behavior or didn't regress something else.

## Proposed approach

Build `tests/test_news_intelligence.py` with deterministic synthetic fixtures — no LLM calls, no live DB, no network. Patch out the LLM by injecting pre-canned event dicts. Use an in-memory SQLite connection. Cover:

**Hashing / cache invalidation**
- Same articles → same hash → `get_cached_news_summaries_today` returns cached result
- New article → different hash → cache miss

**Event identity / deduplication**
- Same underlying story from 5 outlets → one event cluster with `source_count = 5`

**Trend state machine** (these are the 0590 bug targets)
- First negative event on a ticker → NEW
- Repeated distinct events (distinct fingerprints) over 30d → CONFIRMING → ACCELERATING
- Negative history + first positive event → REVERSING (not NEW)
- Ticker with prior active events, no events today → FADING / RESOLVED sweep marks them

**Scoring / ranking**
- 5% holding with high signal_strength ranks below 10% holding with comparable signal_strength (portfolio_priority ordering)
- `signal_strength` threshold correctly classifies into Emerging Risk bucket regardless of position size

**Portfolio themes**
- Three unrelated EARNINGS events (different causal_driver) → no theme fires
- Three tickers with `causal_driver = USD_STRENGTH`, same direction → theme fires

**Thesis mapping**
- Event relevant to a known pillar → `thesis_relevance > 0.25`, correct `component_name`
- Unrelated event → `thesis_relevance` near zero

**Episode immutability**
- `news_state` snapshot captured at episode creation time is unchanged after a subsequent news refresh for the same ticker

## Touches

- `tests/test_news_intelligence.py` — new file
- `agents/news/intelligence.py` — minor refactors to make functions testable with injected fixtures if needed (no logic changes)

## Done when

- [ ] `tests/test_news_intelligence.py` exists and all tests pass via `pytest`
- [ ] Hash/cache invalidation tests pass
- [ ] All trend state machine transitions listed above have a test case
- [ ] Scoring rank ordering (position weight effect) is tested
- [ ] Portfolio theme logic: false positive test and true positive test both pass
- [ ] Thesis mapping coverage and non-coverage cases tested
- [ ] Episode news_state immutability test passes
- [ ] No LLM calls, no network, no live DB required to run the suite
